import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ResourceConflictError
from app.core.security import get_password_hash, verify_password
from app.main import app
from app.models import AuditLog, User
from app.services.admin_service import AdminService
from app.services.storage_quota_service import StorageQuotaService
from app.services.storage_service import StorageService


@pytest.fixture
def client(db):
    for identity in (1, 2):
        db.get(User, identity).password_hash = get_password_hash("test-password-123")
    db.get(User, 1).role_id = 1
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def login(client, email="owner@example.com", password="test-password-123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["data"]["token"]}


@pytest.mark.parametrize("path", ["/auth/register", "/auth/send_code"])
def test_public_registration_is_always_closed(client, db, monkeypatch, path):
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "configured-but-registration-stays-closed")
    before = db.query(User).count()
    response = client.post(
        path, json={"email": "new@example.com", "password": "password", "code": "123456"}
    )
    assert response.status_code == 403 and "管理员" in response.json()["message"]
    assert db.query(User).count() == before
    capabilities = client.get("/platform/capabilities").json()["data"]
    assert (
        capabilities["email_registration"] is False
        and capabilities["account_creation"] == "admin_only"
    )


def test_only_admin_can_create_an_account(client, db):
    body = {"email": "managed@example.com"}
    assert client.post("/admin/users", json=body).status_code == 401
    assert (
        client.post(
            "/admin/users", headers=login(client, "other@example.com"), json=body
        ).status_code
        == 403
    )
    assert db.query(User).count() == 2


def test_creation_initial_login_password_change_and_default_storage(client, db):
    existing_hash = db.get(User, 2).password_hash
    response = client.post(
        "/admin/users", headers=login(client), json={"email": "  NEW-MANAGED@Example.com  "}
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert (
        result["email"] == "new-managed@example.com"
        and result["role"] == "user"
        and result["balance"] == 0
    )
    user = db.get(User, result["user_id"])
    assert user.password_hash != settings.INITIAL_ACCOUNT_PASSWORD and verify_password(settings.INITIAL_ACCOUNT_PASSWORD, user.password_hash)
    assert "password" not in result and "password_hash" not in result
    assert StorageService.user_root(user.id).is_dir()
    headers = login(client, user.email, settings.INITIAL_ACCOUNT_PASSWORD)
    assert client.get("/storage/list", headers=headers).status_code == 200
    assert (
        client.get("/resource/usage", headers=headers).json()["data"]["storage_share_percent"]
        == settings.DEFAULT_STORAGE_SHARE_PERCENT
    )
    changed = client.post(
        "/account/password",
        headers=headers,
        json={"old_password": settings.INITIAL_ACCOUNT_PASSWORD, "new_password": "Changed123"},
    )
    assert changed.status_code == 200
    assert (
        client.post("/auth/login", json={"email": user.email, "password": settings.INITIAL_ACCOUNT_PASSWORD}).status_code
        == 401
    )
    assert login(client, user.email, "Changed123")
    assert db.get(User, 2).password_hash == existing_hash
    actions = db.query(AuditLog).order_by(AuditLog.id).all()
    assert [row.action for row in actions] == ["创建用户", "修改密码"]
    assert actions[0].user_id == 1 and actions[1].user_id == user.id
    assert "Changed123" not in json.dumps([row.detail for row in actions])


def test_duplicate_normalized_email_does_not_reset_password_or_add_audit(client, db):
    headers = login(client)
    body = {"email": "managed@example.com"}
    created = client.post("/admin/users", headers=headers, json=body).json()["data"]
    user = db.get(User, created["user_id"])
    user.password_hash = get_password_hash("Personal123")
    db.commit()
    response = client.post("/admin/users", headers=headers, json={"email": "MANAGED@EXAMPLE.COM"})
    assert response.status_code == 409 and verify_password("Personal123", user.password_hash)
    assert db.query(User).count() == 3 and db.query(AuditLog).count() == 1


@pytest.mark.parametrize(
    "body",
    [
        {"email": "bad"},
        {"email": "x" * 120 + "@example.com"},
        {"email": "new@example.com", "role": "admin"},
        {"email": "new@example.com", "password": "custom"},
    ],
)
def test_creation_validates_email_and_disallows_overriding_defaults(client, db, body):
    assert client.post("/admin/users", headers=login(client), json=body).status_code == 422
    assert db.query(User).count() == 2 and db.query(AuditLog).count() == 0


def test_storage_initialization_failure_rolls_back_account_and_audit(client, db, monkeypatch):
    monkeypatch.setattr(
        StorageQuotaService,
        "prepare",
        Mock(side_effect=ResourceConflictError("Storage unavailable")),
    )
    response = client.post("/admin/users", headers=login(client), json={"email": "new@example.com"})
    assert response.status_code == 409
    assert db.query(User).count() == 2 and db.query(AuditLog).count() == 0


def test_unique_index_conflict_is_recoverable_and_does_not_leave_partial_account(db, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(
            db, "flush", Mock(side_effect=IntegrityError("insert", {}, Exception("duplicate")))
        )
        with pytest.raises(ResourceConflictError, match="已存在"):
            AdminService.create_user(db, db.get(User, 1), "new@example.com")
    assert db.query(User).count() == 2 and db.query(AuditLog).count() == 0
