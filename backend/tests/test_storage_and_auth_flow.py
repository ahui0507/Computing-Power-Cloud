from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_password_hash, create_refresh_token
from app.main import app
from app.models import User, UserStatus, BillingRecord, GPUStatus, GPU
from app.infrastructure.kubernetes.status import PodStatus
from app.services.k8s_service import K8sService
from app.services.jupyter_service import JupyterService
from app.services.storage_service import StorageService


@pytest.fixture
def client(db):
    for identity in (1, 2):
        db.get(User, identity).password_hash = get_password_hash("test-password-123")
    db.commit()

    def database():
        yield db

    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app, raise_server_exceptions=False) as value:
            yield value
    finally:
        app.dependency_overrides.clear()


def headers(client, email="owner@example.com"):
    response = client.post("/auth/login", json={"email": email, "password": "test-password-123"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["data"]["token"]}


def test_login_upload_instance_access_release_and_download(client, db, monkeypatch):
    owner = headers(client)
    other = headers(client, "other@example.com")
    payload = b"training-data,42\n"
    response = client.post(
        "/storage/upload", headers=owner, files={"file": ("data.csv", payload, "text/csv")}
    )
    assert response.status_code == 200
    assert response.json()["data"]["path"] == "data.csv"
    assert (StorageService.user_root(1) / "data.csv").read_bytes() == payload
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "pending"}))
    delete = AsyncMock()
    monkeypatch.setattr(K8sService, "delete_pod", delete)
    state = PodStatus("running", started_at=datetime.utcnow() - timedelta(minutes=10))
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value=state))
    created = client.post(
        "/resource/apply", headers=owner, json={"pool_id": 1, "gpu_count": 1, "image_id": 1}
    )
    assert created.status_code == 200
    identifier = created.json()["data"]["container_id"]
    instance = client.get("/resource/my", headers=owner, params={"refresh": True}).json()["data"][0]
    assert instance["status"] == "running"
    assert "?token=" in instance["jupyter_url"]
    assert instance["start_time"].endswith("+00:00")
    assert client.get("/resource/my", headers=other).json()["data"] == []
    assert (
        client.post(
            "/resource/release", headers=other, json={"container_id": identifier}
        ).status_code
        == 404
    )
    assert (
        client.get("/storage/download", headers=other, params={"path": "data.csv"}).status_code
        == 404
    )
    for _ in range(2):
        released = client.post(
            "/resource/release", headers=owner, json={"container_id": identifier}
        )
        assert released.status_code == 200
    delete.assert_called_once()
    assert db.query(BillingRecord).count() == 1
    assert db.query(GPU).filter(GPU.status == GPUStatus.FREE).count() == 2
    assert (
        client.get("/storage/download", headers=owner, params={"path": "data.csv"}).content
        == payload
    )
    assert client.get("/billing/records", headers=owner).json()["data"][0]["amount"] > 0
    assert client.get("/billing/price").json()["data"]["k80"] == 5.0


@pytest.mark.parametrize("path", ["../user_2/private.txt", "/etc/passwd", "C:\\private.txt"])
def test_file_paths_cannot_escape_user_workspace(client, path):
    response = client.get("/storage/download", headers=headers(client), params={"path": path})
    assert response.status_code == 403


def test_upload_download_and_delete_use_the_same_relative_path(client):
    owner = headers(client)
    client.post("/storage/upload", headers=owner, files={"file": ("文件.txt", b"content")})
    listing = client.get("/storage/list", headers=owner).json()["data"]
    assert listing[0]["path"] == "文件.txt"
    downloaded = client.get("/storage/download", headers=owner, params={"path": "文件.txt"})
    assert downloaded.content == b"content"
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    assert (
        client.post("/storage/delete", headers=owner, json={"path": "文件.txt"}).status_code == 200
    )
    assert client.get("/storage/list", headers=owner).json()["data"] == []


def test_upload_size_limit_removes_partial_files(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 3)
    owner = headers(client)
    response = client.post("/storage/upload", headers=owner, files={"file": ("large.bin", b"1234")})
    assert response.status_code == 413
    assert list(StorageService.user_root(1).iterdir()) == []


def test_symbolic_link_cannot_read_another_users_files(client):
    (StorageService.user_root(2) / "private.txt").write_text("private", encoding="utf-8")
    try:
        (StorageService.user_root(1) / "link.txt").symlink_to(
            StorageService.user_root(2) / "private.txt"
        )
    except OSError:
        pytest.skip("System does not permit creating symbolic links")
    response = client.get("/storage/download", headers=headers(client), params={"path": "link.txt"})
    assert response.status_code == 403


def test_disabled_users_and_refresh_tokens_cannot_access_resources(client, db):
    token = headers(client)
    db.get(User, 1).status = UserStatus.BANNED
    db.commit()
    assert client.get("/resource/my", headers=token).status_code == 403
    refresh = create_refresh_token({"sub": "2"})
    assert (
        client.get("/resource/my", headers={"Authorization": "Bearer " + refresh}).status_code
        == 401
    )


def test_instance_tokens_are_stable_and_distinct():
    assert JupyterService.token(1, 1) == JupyterService.token(1, 1)
    assert JupyterService.token(1, 1) != JupyterService.token(1, 2)
    assert JupyterService.token(1, 1) != JupyterService.token(2, 1)


def test_negative_recharge_is_rejected(client):
    response = client.post("/billing/recharge", headers=headers(client), json={"amount": -10})
    assert response.status_code == 403


@pytest.mark.parametrize("amount", ["NaN", "Infinity"])
def test_non_finite_recharge_is_rejected_without_serialization_error(client, amount):
    response = client.post(
        "/billing/recharge",
        headers=headers(client),
        content='{"amount": ' + amount + "}",
    )
    assert response.status_code == 403
