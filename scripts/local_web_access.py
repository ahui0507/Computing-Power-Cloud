"""Local browser access through the authorized control-node SSH connection."""
from pathlib import Path
import atexit
import os
import re
import select
import socketserver
import threading

import paramiko

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.ops'
LOCAL = ('127.0.0.1', 18080)
DESTINATION = ('127.0.0.1', 8080)


def credentials():
    record = (ROOT / '账号密码.txt').read_text(encoding='utf-8-sig')
    section = record.split('[控制节点 SSH]', 1)[1].split('[', 1)[0]
    def field(name):
        result = re.search(r'^' + name + r'：(.+)$', section, re.M)
        if not result:
            raise ValueError('Missing control SSH credential field')
        return result.group(1).strip()
    return field('地址'), int(field('端口')), field('用户名'), field('密码')


class Connection:
    def __init__(self):
        self.client = None
        self.lock = threading.Lock()

    def transport(self):
        with self.lock:
            if self.client is not None:
                transport = self.client.get_transport()
                if transport and transport.is_active() and transport.is_authenticated():
                    return transport
                self.client.close()
            host, port, user, password = credentials()
            pins = STATE / f'known_hosts_{port}'
            if not pins.is_file():
                raise RuntimeError('Verified SSH host-key file is missing')
            client = paramiko.SSHClient()
            client.load_host_keys(str(pins))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            try:
                client.connect(host, port=port, username=user, password=password,
                               timeout=12, auth_timeout=15, banner_timeout=15,
                               allow_agent=False, look_for_keys=False)
            except Exception:
                client.close()
                raise
            self.client = client
            transport = client.get_transport()
            transport.set_keepalive(30)
            print('Control SSH connection established; credentials are not logged.', flush=True)
            return transport

    def close(self):
        with self.lock:
            if self.client:
                self.client.close()


connection = Connection()


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        channel = None
        try:
            channel = connection.transport().open_channel(
                'direct-tcpip', DESTINATION, self.client_address, timeout=15)
            if channel is None:
                return
            while True:
                readable, _, _ = select.select([self.request, channel], [], [], 60)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    target = channel if source is self.request else self.request
                    target.sendall(data)
        except Exception as error:
            # Exception text and request contents can contain credentials; log only the class.
            print('Forwarding connection closed: ' + type(error).__name__, flush=True)
        finally:
            if channel is not None:
                channel.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    STATE.mkdir(exist_ok=True)
    pid = STATE / 'local-web-access.pid'
    with Server(LOCAL, Forward) as server:
        connection.transport()
        pid.write_text(str(os.getpid()), encoding='ascii')
        def cleanup():
            connection.close()
            if pid.exists() and pid.read_text(encoding='ascii').strip() == str(os.getpid()):
                pid.unlink()
        atexit.register(cleanup)
        print('Browser access ready: http://127.0.0.1:18080', flush=True)
        server.serve_forever(poll_interval=0.5)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as error:
        print('Local browser access failed: ' + type(error).__name__, flush=True)
        raise SystemExit(1)
