import json
import subprocess
import sys
from types import SimpleNamespace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import get_password_hash, verify_password
from app.models import User, Allocation, AllocationStatus, Image
from app.models.audit import AuditLog
from app.services.job_service import JobService, RUNNER
from app.services.storage_service import StorageService
from app.core.config import settings


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def allocation(db, status=AllocationStatus.ACTIVE):
    row = Allocation(request_id=uuid4().hex, user_id=1, pool_id=1, image_id=1,
                     node_id=1, requested_gpu_count=1, status=status,
                     container_id="owned-instance", pod_name="owned-pod")
    db.add(row)
    db.commit()
    return row


def test_password_changes_actual_hash_and_rejects_wrong_current_password(client, db):
    user = db.get(User, 1)
    user.password_hash = get_password_hash("Original123")
    db.commit()
    assert client.post("/account/password", json={"old_password": "wrong", "new_password": "Changed123"}).status_code == 409
    assert verify_password("Original123", user.password_hash)
    result = client.post("/account/password", json={"old_password": "Original123", "new_password": "Changed123"})
    assert result.status_code == 200
    assert verify_password("Changed123", user.password_hash)
    assert not verify_password("Original123", user.password_hash)
    assert db.query(AuditLog).one().action == "修改密码"
    assert "Original123" not in json.dumps(db.query(AuditLog).one().detail)


def test_password_rejects_weak_or_overlong_bytes(client):
    for value in ["abcdefgh", "12345678", "a1" + "汉" * 30]:
        assert client.post("/account/password", json={"old_password": "old", "new_password": value}).status_code == 422


def test_public_keys_validate_fingerprint_duplicate_and_ownership(client, db):
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    first = client.post("/account/keys", json={"name": "laptop", "public_key": public})
    assert first.status_code == 200
    key_id = first.json()["data"]["id"]
    assert client.get("/account/keys").json()["data"][0]["fingerprint"].startswith("SHA256:")
    assert client.post("/account/keys", json={"name": "again", "public_key": public}).status_code == 409
    assert client.post("/account/keys", json={"name": "bad", "public_key": "ssh-rsa invalid-content"}).status_code == 409
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.get("/account/keys").json()["data"] == []
    assert client.post("/account/keys/delete", json={"id": key_id}).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    assert client.post("/account/keys/delete", json={"id": key_id}).status_code == 200
    assert client.get("/account/keys").json()["data"] == []


def test_folder_creation_rejects_escape_and_duplicate(client):
    assert client.post("/storage/folder", json={"path": "../escape"}).status_code == 403
    assert client.post("/storage/folder", json={"path": "project"}).status_code == 200
    assert client.post("/storage/folder", json={"path": "project"}).status_code == 409
    assert client.post("/storage/folder", json={"path": "project/data"}).status_code == 200
    assert client.post("/storage/delete", json={"path": "project"}).status_code == 409


def test_image_catalogue_delete_and_snapshot_honesty(client, db):
    assert client.post("/images/delete", json={"id": 2}).status_code == 404
    assert client.post("/images/delete", json={"id": 1}).status_code == 404
    result = client.post("/images/register", json={"name": "registry.example.com/ml/workbench", "tag": "v1", "desc": "test"})
    assert result.status_code == 200
    image_id = result.json()["data"]["image_id"]
    row = allocation(db)
    row.image_id = image_id
    db.commit()
    assert client.post("/images/delete", json={"id": image_id}).status_code == 409
    row.status = AllocationStatus.RELEASED
    row.end_time = datetime(2026, 10, 10, 8, 0, 0)
    db.commit()
    assert client.post("/images/delete", json={"id": image_id}).status_code == 200
    assert db.get(Image, image_id) is None
    assert client.post("/images/save", json={"container_id": row.container_id, "name": "fake", "tag": "v1"}).status_code == 409


def test_admin_routes_are_protected_and_last_admin_is_kept(client, db):
    assert client.get("/admin/audit").status_code == 403
    assert client.post("/admin/delete_pool", json={"id": 1}).status_code == 403
    user = db.get(User, 1)
    user.role_id = 1
    db.commit()
    db.expire_all()
    assert client.post("/admin/set_role", json={"user_id": 1, "role": "user"}).status_code == 409
    row = allocation(db)
    assert client.post("/admin/delete_pool", json={"id": 1}).status_code == 409
    row.status = AllocationStatus.RELEASED
    db.commit()
    assert client.post("/admin/delete_pool", json={"id": 1}).status_code == 200
    result = client.get("/admin/audit", params={"action": "删除", "page_size": 1})
    assert result.status_code == 200
    assert result.json()["data"]["total"] == 1
    assert result.json()["data"]["items"][0]["resource"] == "pool/1"
    assert client.get("/admin/audit", params={"start": "invalid"}).status_code == 409


def test_jobs_execute_once_show_results_and_cannot_cross_users(client, db, monkeypatch):
    row = allocation(db)
    job_id = uuid4().hex
    calls = []

    def execute(allocation, command):
        calls.append(command)
        JobService.write(1, JobService.relative(job_id, "pid.json"), '{"pid":123,"started_at":"2026-10-10T08:00:00Z"}')
        return "started"

    monkeypatch.setattr(JobService, "execute", execute)
    body = {"job_id": job_id, "container_id": row.container_id, "name": "smoke", "command": "python hello.py"}
    assert client.post("/jobs", json=body).status_code == 200
    assert client.post("/jobs", json=body).status_code == 200
    assert len(calls) == 1
    assert client.post("/jobs", json={**body, "command": "different"}).status_code == 409
    assert client.get("/jobs").json()["data"][0]["status"] == "running"
    JobService.write(1, JobService.relative(job_id, "output.log"), "Hello compute\n2\n")
    JobService.write(1, JobService.relative(job_id, "result.json"), '{"exit_code":0,"finished_at":"2026-10-10T08:01:00Z"}')
    assert client.get("/jobs").json()["data"][0]["status"] == "completed"
    assert "Hello compute" in client.get(f"/jobs/{job_id}/logs").json()["data"]["logs"]
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.get("/jobs").json()["data"] == []
    assert client.get(f"/jobs/{job_id}/logs").status_code == 404
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 404


def test_released_instance_cannot_accept_job(client, db):
    row = allocation(db, AllocationStatus.RELEASED)
    assert client.post("/jobs", json={"job_id": uuid4().hex, "container_id": row.container_id, "name": "bad", "command": "true"}).status_code == 409


def test_admin_node_detail_preserves_list_fields(client, db):
    assert client.get("/cluster/node/1").status_code == 403
    db.get(User, 1).role_id = 1
    db.commit()
    db.expire_all()
    overview = next(row for row in client.get("/cluster/nodes").json()["data"] if row["node_id"] == 1)
    response = client.get("/cluster/node/1")
    assert response.status_code == 200
    detail = response.json()["data"]
    assert {key: detail[key] for key in overview} == overview
    assert len(detail["gpu_list"]) == overview["gpus_total"]
    assert detail["telemetry_state"] == "missing"
    assert {row["status"] for row in detail["gpu_list"]} == {"unknown"}


def test_image_availability_uses_actual_node_cache_and_private_ownership(client, monkeypatch):
    from app.routers import console
    from app.infrastructure.kubernetes import client as kube_client
    api = SimpleNamespace(close=lambda: None)
    node = SimpleNamespace(metadata=SimpleNamespace(name="worker-a"), status=SimpleNamespace(images=[SimpleNamespace(names=["docker.io/library/test-jupyter:v1", "private-jupyter:v1"])]))
    core = SimpleNamespace(api_client=api, list_node=lambda **kwargs: SimpleNamespace(items=[node]))
    monkeypatch.setattr(kube_client, "create_clients", lambda: (core, SimpleNamespace(api_client=api)))
    monkeypatch.setattr(settings, "K8S_IMAGE_PULL_POLICY", "Never")
    assert client.get("/images/availability").json()["data"] == {"1": [1]}
    assert console.normalized_image("jupyter-test:latest") == "docker.io/library/jupyter-test:latest"
    assert console.normalized_image("team/image:v1") == "docker.io/team/image:v1"
    assert client.post("/images/register", json={"name": "repo/image:v1", "tag": "v1"}).status_code == 422


def test_jobs_cancel_and_released_instance_interrupt_states(client, db, monkeypatch):
    row = allocation(db)
    job_id = uuid4().hex
    def execute(allocation, command):
        if "killpg" in command:
            return "cancelled"
        JobService.write(1, JobService.relative(job_id, "pid.json"), '{"pid":123}')
        return "started"
    monkeypatch.setattr(JobService, "execute", execute)
    body = {"job_id": job_id, "container_id": row.container_id, "name": "long", "command": "sleep 90"}
    assert client.post("/jobs", json=body).status_code == 200
    assert client.post(f"/jobs/{job_id}/cancel").json()["data"]["status"] == "cancelled"
    job_id = uuid4().hex
    assert client.post("/jobs", json={**body, "job_id": job_id}).status_code == 200
    row.status = AllocationStatus.RELEASED
    row.end_time = datetime(2026, 10, 10, 8, 0, 0)
    db.commit()
    rows = client.get("/jobs").json()["data"]
    assert any(item["status"] == "interrupted" for item in rows)
    assert next(item for item in rows if item["status"] == "interrupted")["finished_at"].endswith("+00:00")


@pytest.mark.parametrize("command,code,output", [("printf 'hello\\n'; exit 0", 0, "hello"), ("printf 'failed\\n'; exit 7", 7, "failed")])
def test_actual_runner_captures_exit_code_and_output(tmp_path, command, code, output):
    if sys.platform == "win32":
        pytest.skip("生产任务运行器使用 Linux bash")
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER.replace('cwd="/workspace"', f"cwd={str(tmp_path)!r}"))
    (tmp_path / "metadata.json").write_text(json.dumps({"command": command}))
    subprocess.run([sys.executable, str(runner)], check=True, timeout=10)
    assert json.loads((tmp_path / "result.json").read_text())["exit_code"] == code
    assert output in (tmp_path / "output.log").read_text()
