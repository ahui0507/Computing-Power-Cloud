#!/usr/bin/env python3
"""Run with Python 3.10+: python platform-ssh.py. Uses only the standard library.

Keep this window open; connect SSH/SFTP/VS Code to the printed localhost port.
Credentials stay in memory. Each SSH connection still authenticates to the instance.
"""
import argparse
import base64
import getpass
import hashlib
import json
import os
import socket
import socketserver
import ssl
import struct
import threading
import urllib.request
from urllib.parse import quote, urlsplit

DEFAULT_URL = ""
DEFAULT_INSTANCE = ""
MAX_FRAME = 1024 * 1024


def exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


class WebSocket:
    def __init__(self, url, instance, token):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise ValueError("Use the platform HTTP or HTTPS website URL")
        self.sock = socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)), 15)
        self.lock = threading.Lock()
        try:
            if parsed.scheme == "https":
                self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=parsed.hostname)
            key = base64.b64encode(os.urandom(16)).decode()
            path = parsed.path.rstrip("/") + "/api/resource/" + quote(instance, safe="") + "/ssh-tunnel"
            request = (f"GET {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                       f"Authorization: Bearer {token}\r\n\r\n")
            self.sock.sendall(request.encode("ascii"))
            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                header.extend(exact(self.sock, 1))
                if len(header) > 16384:
                    raise ValueError("Invalid handshake")
            lines = header.decode("latin1").split("\r\n")
            headers = {name.lower(): value.strip() for name, value in (line.split(":", 1) for line in lines[1:] if ":" in line)}
            accepted = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if lines[0].split()[1] != "101" or headers.get("sec-websocket-accept") != accepted:
                raise ConnectionError("SSH tunnel rejected; check login and instance status")
            self.sock.settimeout(None)
        except BaseException:
            self.sock.close()
            raise

    def send(self, data, opcode=2):
        mask = os.urandom(4)
        size = len(data)
        if size > MAX_FRAME:
            raise ValueError("Oversized frame")
        length = bytes([0x80 | size]) if size < 126 else (
            b"\xfe" + struct.pack("!H", size) if size < 65536 else b"\xff" + struct.pack("!Q", size))
        frame = bytes([0x80 | opcode]) + length + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        with self.lock:
            self.sock.sendall(frame)

    def receive(self):
        while True:
            first, second = exact(self.sock, 2)
            opcode, size = first & 15, second & 127
            if first & 0x70 or second & 0x80:
                raise ValueError("Invalid server frame")
            if size == 126:
                size = struct.unpack("!H", exact(self.sock, 2))[0]
            elif size == 127:
                size = struct.unpack("!Q", exact(self.sock, 8))[0]
            if size > MAX_FRAME or (opcode >= 8 and (size > 125 or not first & 0x80)):
                raise ValueError("Oversized server frame")
            data = exact(self.sock, size)
            if opcode == 8:
                raise EOFError
            if opcode == 9:
                self.send(data, 10)
            elif opcode in (0, 2):
                return data
            elif opcode != 10:
                raise ValueError("Unsupported server frame")

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def api(url, path, data, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url.rstrip("/") + "/api" + path, data=json.dumps(data).encode(), headers=headers)
    # Match direct campus access; environment proxy variables must not divert credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        value = json.load(response)
    if value.get("code", 200) != 200:
        raise ConnectionError("Platform request failed")
    return value["data"]


def serve(url, instance, token, port=0, ready=None):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            bridge = None
            thread = None
            try:
                bridge = WebSocket(url, instance, token)

                def upstream():
                    try:
                        while data := self.request.recv(65536):
                            bridge.send(data)
                    except (OSError, EOFError):
                        pass
                    finally:
                        bridge.close()

                thread = threading.Thread(target=upstream, daemon=True)
                thread.start()
                while True:
                    self.request.sendall(bridge.receive())
            except (OSError, EOFError, ValueError):
                pass
            finally:
                if bridge:
                    bridge.close()
                try:
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                if thread:
                    thread.join(timeout=2)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    with Server(("127.0.0.1", port), Handler) as server:
        actual_port = server.server_address[1]
        print(f"SSH ready: ssh -p {actual_port} root@127.0.0.1", flush=True)
        print("Use the instance SSH password shown on the website. Keep this window open.", flush=True)
        if ready:
            ready(server)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or not args.instance:
        parser.error("Provide --url http://platform:port and --instance ID")
    email = input("Platform email: ").strip()
    password = getpass.getpass("Platform login password: ")
    try:
        token = api(args.url, "/auth/login", {"email": email, "password": password})["token"]
        del password
        api(args.url, "/resource/" + quote(args.instance, safe="") + "/ssh", {}, token)
        # Fail before reporting readiness if authentication or routing is unavailable.
        probe = WebSocket(args.url, args.instance, token)
        probe.close()
        serve(args.url, args.instance, token, args.port)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"Connection failed ({type(error).__name__}). Check the website address, account and instance status.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
