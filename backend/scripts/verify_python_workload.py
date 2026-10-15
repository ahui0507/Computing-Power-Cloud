"""普通用户在真实实例中运行 .py 文件；账号 JSON 通过标准输入传入。

prepare 申请实例并上传示例；execute 通过 Jupyter 终端和 Python 内核运行文件；
release 释放实例并确认输出文件仍可下载。state/report 不保存密码或访问令牌。
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import sys
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from websocket import create_connection


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "execute", "release"])
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--pool-id", type=int, default=1)
    parser.add_argument("--image-id", type=int, default=22)
    parser.add_argument("--state", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--require-existing-terminal", action="store_true")
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=120) as client:
        login = client.post("/auth/login", json=credentials)
        check(login.status_code == 200, "Ordinary user login failed")
        client.headers["Authorization"] = "Bearer " + login.json()["data"]["token"]
        owner = client.get("/auth/user_info").json()["data"]
        check(owner["role"] == "user", "Use an ordinary user for the Python file test")

        def save():
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            Path(args.report).write_text(json.dumps(state, indent=2), encoding="utf-8")

        def current():
            rows = client.get("/resource/my").json()["data"]
            return next(r for r in rows if r["container_id"] == state["container_id"])

        def wait(status):
            deadline = time.monotonic() + 180
            while True:
                row = current()
                check(row["status"] != "failed", "Workload failed")
                if row["status"] == status:
                    return row
                check(time.monotonic() < deadline, "Workload state change timed out")
                time.sleep(1)

        if args.phase == "prepare":
            check(
                not state.get("container_id") or state.get("released"),
                "Previous test instance needs release first",
            )
            run_id = uuid.uuid4().hex[:8]
            source = (
                Path(__file__).resolve().parents[2] / "test-images/jupyter-test/hello_platform.py"
            ).read_text()
            pools = client.get("/resource/pools").json()["data"]
            free = next(p["free_gpus"] for p in pools if p["pool_id"] == args.pool_id)
            state = {
                "passed": False,
                "user_id": owner["user_id"],
                "role": owner["role"],
                "run_id": run_id,
                "source_filename": f"hello_platform_{run_id}.py",
                "output_filename": f"hello_output_{run_id}.txt",
                "initial_free_gpus": free,
                "expected_output": "Hello, cloud platform!\n1 + 1 = 2\n",
                "released": False,
            }
            applied = client.post(
                "/resource/apply",
                headers={"Idempotency-Key": "python-file-" + run_id},
                json={"pool_id": args.pool_id, "image_id": args.image_id, "gpu_count": 1},
            )
            check(applied.status_code == 200, "Resource application failed")
            state["container_id"] = applied.json()["data"]["container_id"]
            save()
            wait("running")
            uploaded = client.post(
                "/storage/upload", files={"file": (state["source_filename"], source.encode())}
            )
            check(uploaded.status_code == 200, "Python file upload failed")
            state["source_code"] = source
            state["prepared"] = True
            save()
            print(
                json.dumps(
                    {
                        "phase": "prepared",
                        "container_id": state["container_id"],
                        "source_filename": state["source_filename"],
                        "role": owner["role"],
                    }
                ),
                flush=True,
            )
            return 0

        check(state.get("user_id") == owner["user_id"], "Test state belongs to a different user")
        if args.phase == "execute":
            state["passed"] = False
            state["execution_passed"] = False
            for field in ("terminal_exit_code", "terminal_stdout", "terminal_name",
                          "browser_terminal_verified", "kernel_execution"):
                state.pop(field, None)
            execution_id = uuid.uuid4().hex[:12]
            save()
            row = wait("running")
            url = urlsplit(row["jupyter_url"])
            token = parse_qs(url.query)["token"][0]
            base = urlunsplit((url.scheme, url.netloc, url.path.rstrip("/") + "/", "", ""))
            auth = {"Authorization": "token " + token}
            terminals = client.get(base + "api/terminals", headers=auth)
            check(terminals.status_code == 200, "Jupyter terminal API unavailable")
            available = terminals.json()
            if not available:
                check(
                    not args.require_existing_terminal, "The browser did not create a real terminal"
                )
                created = client.post(base + "api/terminals", headers=auth)
                check(
                    created.status_code == 200 or created.status_code == 201,
                    "Could not create terminal",
                )
                available = [created.json()]
            terminal = available[0]["name"]
            endpoint = base.replace("http://", "ws://").replace("https://", "wss://")
            channel = create_connection(
                endpoint + "terminals/websocket/" + terminal + "?" + urlencode({"token": token}),
                origin=url.scheme + "://" + url.netloc,
                timeout=30,
            )
            # 新连接会重放终端历史，每次执行必须使用不同的完成标识。
            marker = "__PYTHON_FILE_EXIT_" + execution_id + "__"
            command = (
                "cd /workspace && python "
                + shlex.quote(state["source_filename"])
                + " > "
                + shlex.quote(state["output_filename"])
                + "; platform_python_exit=$?; cat "
                + shlex.quote(state["output_filename"])
                + "; printf '\\n"
                + marker
                + '=%s\\n\' "$platform_python_exit"\n'
            )
            transcript = ""
            try:
                channel.send(json.dumps(["set_size", 24, 100, 0, 0]))
                channel.send(json.dumps(["stdin", command]))
                deadline = time.monotonic() + 45
                exit_code = None
                while time.monotonic() < deadline:
                    message = json.loads(channel.recv())
                    if message[0] == "stdout":
                        transcript += message[1]
                        match = re.search(re.escape(marker) + r"=(\d+)", transcript)
                        if match:
                            exit_code = int(match.group(1))
                            break
                check(exit_code == 0, "Python file failed in the real terminal")
            finally:
                channel.close()
            downloaded = client.get("/storage/download", params={"path": state["output_filename"]})
            check(
                downloaded.status_code == 200 and downloaded.text == state["expected_output"],
                "Terminal output file could not be downloaded correctly",
            )
            state.update(
                {
                    "terminal_exit_code": exit_code,
                    "terminal_stdout": downloaded.text,
                    "terminal_name": terminal,
                    "browser_terminal_verified": args.require_existing_terminal,
                }
            )
            created = client.post(base + "api/kernels", headers=auth, json={"name": "python3"})
            check(created.status_code == 201, "Python kernel could not start")
            kernel = created.json()["id"]
            session, message_id = uuid.uuid4().hex, uuid.uuid4().hex
            channel = create_connection(
                endpoint
                + "api/kernels/"
                + kernel
                + "/channels?"
                + urlencode({"token": token, "session_id": session}),
                origin=url.scheme + "://" + url.netloc,
                timeout=30,
            )
            code = (
                "import subprocess, sys, os, json\n"
                + f"p = subprocess.run([sys.executable, '/workspace/{state['source_filename']}'], capture_output=True, text=True)\n"
                + "print(json.dumps({'stdout': p.stdout, 'stderr': p.stderr, 'exit_code': p.returncode, 'python_version': sys.version.split()[0], 'working_directory': os.getcwd()}))"
            )
            try:
                channel.send(
                    json.dumps(
                        {
                            "header": {
                                "msg_id": message_id,
                                "session": session,
                                "username": "acceptance",
                                "date": datetime.now(timezone.utc).isoformat(),
                                "msg_type": "execute_request",
                                "version": "5.3",
                            },
                            "parent_header": {},
                            "metadata": {},
                            "channel": "shell",
                            "buffers": [],
                            "content": {
                                "code": code,
                                "silent": False,
                                "store_history": False,
                                "user_expressions": {},
                                "allow_stdin": False,
                            },
                        }
                    )
                )
                output, reply, idle = [], False, False
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    message = json.loads(channel.recv())
                    if message.get("parent_header", {}).get("msg_id") != message_id:
                        continue
                    kind = message["header"]["msg_type"]
                    if kind == "stream" and message["content"]["name"] == "stdout":
                        output.append(message["content"]["text"])
                    if kind == "execute_reply":
                        reply = message["content"]["status"] == "ok"
                    if kind == "status" and message["content"].get("execution_state") == "idle":
                        idle = True
                    if reply and idle:
                        break
                check(reply and idle, "Python kernel execution failed")
                result = json.loads("".join(output).strip())
                check(
                    result["exit_code"] == 0
                    and result["stdout"] == state["expected_output"]
                    and result["stderr"] == "",
                    "Python file did not run successfully from the Python kernel",
                )
                state["kernel_execution"] = result
            finally:
                channel.close()
                client.delete(base + "api/kernels/" + kernel, headers=auth)
            state["execution_passed"] = True
            state["successful_executions"] = state.get("successful_executions", 0) + 1
            save()
            print(
                json.dumps(
                    {
                        "phase": "executed",
                        "terminal_exit_code": 0,
                        "stdout": state["terminal_stdout"],
                        "kernel_execution": state["kernel_execution"],
                    }
                ),
                flush=True,
            )
            return 0

        released = client.post("/resource/release", json={"container_id": state["container_id"]})
        check(released.status_code == 200, "Test instance release failed")
        wait("released")
        for key in ("source_filename", "output_filename"):
            response = client.get("/storage/download", params={"path": state[key]})
            expected = (
                state["source_code"] if key == "source_filename" else state["expected_output"]
            )
            check(
                response.status_code == 200 and response.text == expected,
                "Demo file was lost after release",
            )
        bills = [
            b
            for b in client.get("/billing/records").json()["data"]
            if b["container_id"] == state["container_id"]
        ]
        check(len(bills) == 1, "Test instance did not have exactly one bill")
        pools = client.get("/resource/pools").json()["data"]
        free = next(p["free_gpus"] for p in pools if p["pool_id"] == args.pool_id)
        check(free == state["initial_free_gpus"], "GPU capacity did not recover after release")
        state.update(
            {
                "released": True,
                "files_persist_after_release": True,
                "billing_records": 1,
                "final_free_gpus": free,
                "passed": bool(state.get("execution_passed")),
            }
        )
        save()
        print(
            json.dumps(
                {
                    "phase": "released",
                    "passed": state["passed"],
                    "final_free_gpus": free,
                    "files_persist_after_release": True,
                }
            ),
            flush=True,
        )
        return 0 if state["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
