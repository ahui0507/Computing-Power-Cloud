"""现场验收：登录、文件共享、Jupyter 鉴权、真实 GPU 计算、释放及结算。

创建一个测试实例并产生少量按时计费，结束时释放实例和删除测试文件。
密码通过 PLATFORM_ACCEPT_PASSWORD 环境变量提供，报告不包含令牌或密码。
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, quote

import httpx
from kubernetes.stream import stream

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.kubernetes.client import create_clients
from app.core.config import settings


class AcceptanceError(RuntimeError):
    pass


def execute(arguments):
    password = os.environ.get("PLATFORM_ACCEPT_PASSWORD")
    if not password:
        raise AcceptanceError("Set PLATFORM_ACCEPT_PASSWORD before running acceptance")
    checks, cleanup_errors = [], []
    container_id = None
    filename = f"acceptance_{uuid.uuid4().hex}.txt"
    uploaded = False
    authorized = {}
    failure = None
    with httpx.Client(timeout=30, follow_redirects=True) as client:

        def api(method, path, **kwargs):
            headers = {**authorized, **kwargs.pop("headers", {})}
            response = client.request(
                method, arguments.api_url.rstrip("/") + path, headers=headers, **kwargs
            )
            if response.status_code != 200:
                raise AcceptanceError(f"API {path} returned HTTP {response.status_code}")
            return response

        try:
            if api("GET", "/health").json().get("status") != "healthy":
                raise AcceptanceError("Backend readiness failed")
            checks.append("backend_ready")
            login = api(
                "POST", "/auth/login", json={"email": arguments.email, "password": password}
            ).json()["data"]
            authorized["Authorization"] = "Bearer " + login["token"]
            owner_id = api("GET", "/auth/user_info").json()["data"]["user_id"]
            checks.append("login")
            api("POST", "/storage/upload", files={"file": (filename, b"acceptance-data-42")})
            uploaded = True
            if (
                api("GET", "/storage/download", params={"path": filename}).content
                != b"acceptance-data-42"
            ):
                raise AcceptanceError("Uploaded file could not be downloaded")
            checks.append("file_upload_download")
            application_key = "acceptance-" + uuid.uuid4().hex
            parameters = {
                "pool_id": arguments.pool_id,
                "image_id": arguments.image_id,
                "gpu_count": 1,
            }
            created = api(
                "POST",
                "/resource/apply",
                timeout=120,
                json=parameters,
                headers={"Idempotency-Key": application_key},
            ).json()["data"]
            container_id = created["container_id"]
            repeated = api(
                "POST",
                "/resource/apply",
                json=parameters,
                headers={"Idempotency-Key": application_key},
            ).json()["data"]
            if repeated["container_id"] != container_id:
                raise AcceptanceError("Repeated application created another instance")
            checks.append("idempotent_application")
            deadline = time.monotonic() + arguments.startup_timeout
            while True:
                resources = api("GET", "/resource/my").json()["data"]
                current = next(item for item in resources if item["container_id"] == container_id)
                if current["status"] == "running":
                    break
                if current["status"] == "failed":
                    raise AcceptanceError(
                        "Workload entered failed state; inspect its status message"
                    )
                if time.monotonic() >= deadline:
                    raise AcceptanceError("Workload startup timed out")
                time.sleep(1)
            checks.append("workload_ready")
            url = urlsplit(current["jupyter_url"])
            query = parse_qs(url.query)
            token = query.get("token", [None])[0]
            if not token:
                raise AcceptanceError("Jupyter access token is missing")
            contents_path = url.path.rstrip("/") + "/api/contents/" + quote(filename)
            contents = urlunsplit((url.scheme, url.netloc, contents_path, "", ""))
            if client.get(contents).status_code != 403:
                raise AcceptanceError("Anonymous Jupyter access was not rejected")
            authorized_contents = client.get(contents, params={"token": token, "format": "text"})
            if (
                authorized_contents.status_code != 200
                or authorized_contents.json().get("content") != "acceptance-data-42"
            ):
                raise AcceptanceError("Jupyter cannot read the platform's uploaded file")
            checks.extend(["jupyter_authentication", "shared_workspace"])

            allocation_id = container_id.split("-")[1]
            core, _ = create_clients()
            try:
                pods = core.list_namespaced_pod(
                    settings.K8S_NAMESPACE, label_selector=f"allocation-id={allocation_id}"
                ).items
                own = [pod for pod in pods if pod.metadata.labels.get("user-id") == str(owner_id)]
                if len(own) != 1:
                    raise AcceptanceError("Could not identify the owned GPU workload")
                code_path = (
                    Path(__file__).resolve().parents[2] / "test-images/jupyter-test/gpu_check.py"
                )
                code = code_path.read_text(encoding="utf-8")
                channel = stream(
                    core.connect_get_namespaced_pod_exec,
                    name=own[0].metadata.name,
                    namespace=settings.K8S_NAMESPACE,
                    command=["python", "-c", code],
                    stdout=True,
                    stderr=True,
                    stdin=False,
                    tty=False,
                    _request_timeout=30,
                    _preload_content=False,
                )
                try:
                    # 直接读取 stdout；预加载模式会把 JSON 反序列化后转成 Python repr。
                    channel.run_forever(timeout=30)
                    if channel.is_open():
                        raise AcceptanceError("CUDA computation timed out inside the container")
                    result = channel.read_stdout()
                    if channel.returncode != 0:
                        raise AcceptanceError("CUDA computation failed inside the container")
                finally:
                    channel.close()
                try:
                    gpu = json.loads(result.strip())
                except (ValueError, TypeError):
                    raise AcceptanceError("CUDA computation failed inside the container") from None
                if gpu.get("visible_gpus") != 1 or gpu.get("computed") != 42:
                    raise AcceptanceError("GPU visibility or computation result is incorrect")
                checks.append("gpu_computation")
            finally:
                core.api_client.close()

            api("POST", "/resource/release", timeout=90, json={"container_id": container_id})
            api("POST", "/resource/release", timeout=90, json={"container_id": container_id})
            deadline = time.monotonic() + arguments.release_timeout
            while True:
                resources = api("GET", "/resource/my").json()["data"]
                current = next(item for item in resources if item["container_id"] == container_id)
                if current["status"] == "released":
                    break
                if time.monotonic() >= deadline:
                    raise AcceptanceError("Workload release did not complete before timeout")
                time.sleep(1)
            records = api("GET", "/billing/records").json()["data"]
            related = [item for item in records if item["container_id"] == container_id]
            if len(related) != 1 or related[0]["amount"] <= 0:
                raise AcceptanceError("Release did not produce exactly one positive billing record")
            checks.extend(["resource_release", "idempotent_billing"])
            if (
                api("GET", "/storage/download", params={"path": filename}).content
                != b"acceptance-data-42"
            ):
                raise AcceptanceError("Workspace data was lost after release")
            checks.append("workspace_persistence")
        except Exception as exc:
            failure = str(exc) if isinstance(exc, AcceptanceError) else type(exc).__name__
        finally:
            if container_id:
                try:
                    api(
                        "POST", "/resource/release", timeout=90, json={"container_id": container_id}
                    )
                except Exception:
                    cleanup_errors.append("release_test_instance")
            if uploaded:
                try:
                    api("POST", "/storage/delete", json={"path": filename})
                except Exception:
                    cleanup_errors.append("delete_test_file")
    return {
        "passed": failure is None and not cleanup_errors,
        "checks": checks,
        "failure": failure,
        "cleanup_errors": cleanup_errors,
        "container_id": container_id,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--pool-id", required=True, type=int)
    parser.add_argument("--image-id", required=True, type=int)
    parser.add_argument("--startup-timeout", type=int, default=180)
    parser.add_argument("--release-timeout", type=int, default=180)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    try:
        result = execute(arguments)
    except AcceptanceError as exc:
        result = {"passed": False, "checks": [], "failure": str(exc), "cleanup_errors": []}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.report:
        arguments.report.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
