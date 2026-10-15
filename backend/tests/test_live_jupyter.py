"""启动真实 Jupyter，验证令牌、共享文件和 WebSocket 执行。"""
import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from starlette.datastructures import UploadFile
from websocket import create_connection

from app.infrastructure.kubernetes.manifests import WorkloadSpec, build_pod
from app.services.jupyter_service import JupyterService
from app.services.storage_service import StorageService


def test_real_jupyter_authentication_files_and_kernel_execution(workspace, tmp_path):
    token = JupyterService.token(123, 1)
    directory = StorageService.user_root(1)
    asyncio.run(
        StorageService.upload_file(
            None, 1, UploadFile(filename="uploaded.txt", file=io.BytesIO(b"uploaded from platform"))
        )
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    spec = WorkloadSpec(
        allocation_id=123,
        user_id=1,
        pod_name="pod-123-test",
        image="test",
        gpu_count=1,
        node_name="test",
        namespace="default",
        ingress_enabled=True,
        ingress_host="127.0.0.1",
        ingress_class="traefik",
        use_tls=False,
        image_pull_policy="Never",
        jupyter_command="jupyter-lab",
        jupyter_token=token,
        workspace_claim="test-workspaces",
    )
    arguments = build_pod(spec)["spec"]["containers"][0]["args"]
    arguments = [
        value.replace("$(JUPYTER_TOKEN)", token)
        .replace("--port=8888", f"--port={port}")
        .replace("--ServerApp.root_dir=/workspace", f"--ServerApp.root_dir={directory}")
        .replace("--ip=0.0.0.0", "--ip=127.0.0.1")
        for value in arguments
    ]
    environment = dict(os.environ)
    for variable, child in (
        ("JUPYTER_CONFIG_DIR", "config"),
        ("JUPYTER_RUNTIME_DIR", "runtime"),
        ("IPYTHONDIR", "ipython"),
    ):
        location = tmp_path / child
        location.mkdir()
        environment[variable] = str(location)
    base = f"http://127.0.0.1:{port}/jupyter/123/"
    authorization = {"Authorization": f"token {token}"}
    with (tmp_path / "jupyter.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "jupyterlab", *arguments],
            cwd=directory,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 40
            while True:
                assert process.poll() is None, "Jupyter exited during startup"
                try:
                    response = httpx.get(base + "api/contents", headers=authorization, timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                assert time.monotonic() < deadline, "Jupyter did not become ready"
                time.sleep(0.2)
            assert httpx.get(base + "api/contents", timeout=5).status_code == 403
            wrong_token = JupyterService.token(123, 2)
            assert (
                httpx.get(
                    base + "api/contents", params={"token": wrong_token}, timeout=5
                ).status_code
                == 403
            )
            # 对应前端打开的带令牌 URL，浏览器会取得当前实例的登录身份。
            authorized = httpx.get(base + "api/contents", params={"token": token}, timeout=5)
            assert authorized.status_code == 200
            assert "uploaded.txt" in [entry["name"] for entry in authorized.json()["content"]]
            saved = httpx.put(
                base + "api/contents/from_jupyter.txt",
                headers=authorization,
                json={"type": "file", "format": "text", "content": "saved"},
                timeout=5,
            )
            assert saved.status_code in (200, 201)
            stream, _ = StorageService.open_download(1, "from_jupyter.txt")
            with stream:
                assert stream.read() == b"saved"
            created = httpx.post(
                base + "api/kernels", headers=authorization, json={"name": "python3"}, timeout=15
            )
            assert created.status_code == 201
            kernel_id = created.json()["id"]
            message_id, session_id = uuid.uuid4().hex, uuid.uuid4().hex
            endpoint = (
                base.replace("http://", "ws://")
                + f"api/kernels/{kernel_id}/channels?"
                + urlencode({"token": token, "session_id": session_id})
            )
            channel = create_connection(endpoint, timeout=15, origin=f"http://127.0.0.1:{port}")
            try:
                channel.send(
                    json.dumps(
                        {
                            "header": {
                                "msg_id": message_id,
                                "session": session_id,
                                "username": "test",
                                "date": datetime.now(timezone.utc).isoformat(),
                                "msg_type": "execute_request",
                                "version": "5.3",
                            },
                            "parent_header": {},
                            "metadata": {},
                            "channel": "shell",
                            "content": {
                                "code": "print(6 * 7)",
                                "silent": False,
                                "store_history": False,
                                "user_expressions": {},
                                "allow_stdin": False,
                            },
                            "buffers": [],
                        }
                    )
                )
                output = []
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    message = json.loads(channel.recv())
                    if message.get("parent_header", {}).get("msg_id") != message_id:
                        continue
                    if message["header"]["msg_type"] == "stream":
                        output.append(message["content"]["text"])
                    if message["header"]["msg_type"] == "execute_reply":
                        assert message["content"]["status"] == "ok"
                    if (
                        message["header"]["msg_type"] == "status"
                        and message["content"].get("execution_state") == "idle"
                    ):
                        break
                assert "42" in "".join(output)
            finally:
                channel.close()
                httpx.delete(base + f"api/kernels/{kernel_id}", headers=authorization, timeout=5)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
