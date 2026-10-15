from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ClusterUnavailableError
from app.main import app
from app.models.user import User
from app.services.k8s_service import K8sService


@pytest.fixture
def client(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def authenticate(db):
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)


def test_missing_auth_preserves_http_status_and_header(client):
    response = client.get("/resource/my")
    assert response.status_code == 401
    assert response.json()["code"] == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_gpu_count_is_http_422(client, db, count):
    authenticate(db)
    response = client.post(
        "/resource/apply", json={"pool_id": 1, "gpu_count": count, "image_id": 1}
    )
    assert response.status_code == 422
    assert response.json()["code"] == 422


def test_cluster_unavailable_is_http_503(client, db, monkeypatch):
    authenticate(db)
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(side_effect=ClusterUnavailableError()))
    response = client.post("/resource/apply", json={"pool_id": 1, "gpu_count": 1, "image_id": 1})
    assert response.status_code == 503
    assert response.json()["code"] == 503


def test_create_and_list_use_consistent_pending_status(client, db, monkeypatch):
    authenticate(db)
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "pending"}))
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="pending"))
    created = client.post("/resource/apply", json={"pool_id": 1, "gpu_count": 1, "image_id": 1})
    listed = client.get("/resource/my")
    assert created.status_code == listed.status_code == 200
    assert created.json()["data"]["status"] == listed.json()["data"][0]["status"] == "pending"
    assert listed.json()["data"][0]["start_time"] is None


def test_forbidden_image_preserves_http_403(client, db):
    authenticate(db)
    response = client.post("/resource/apply", json={"pool_id": 1, "gpu_count": 1, "image_id": 2})
    assert response.status_code == 403


def test_unexpected_error_does_not_expose_internal_details(client, db, monkeypatch):
    authenticate(db)
    monkeypatch.setattr(
        K8sService, "create_pod", AsyncMock(side_effect=RuntimeError("private details"))
    )
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    response = client.post("/resource/apply", json={"pool_id": 1, "gpu_count": 1, "image_id": 1})
    assert response.status_code == 500
    assert "private details" not in response.text


def test_custom_validator_error_is_serialized_as_http_422(client):
    response = client.post("/auth/login", json={"email": "invalid", "password": "unused"})
    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert response.json()["data"]["errors"][0]["loc"] == ["body", "email"]


def test_idempotency_header_replays_same_application(client, db, monkeypatch):
    authenticate(db)
    create = AsyncMock(return_value={"status": "pending"})
    monkeypatch.setattr(K8sService, "create_pod", create)
    payload = {"pool_id": 1, "gpu_count": 1, "image_id": 1}
    first = client.post("/resource/apply", headers={"Idempotency-Key": "intent-one"}, json=payload)
    second = client.post("/resource/apply", headers={"Idempotency-Key": "intent-one"}, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["container_id"] == second.json()["data"]["container_id"]
    create.assert_awaited_once()
    changed = client.post(
        "/resource/apply",
        headers={"Idempotency-Key": "intent-one"},
        json={**payload, "gpu_count": 2},
    )
    assert changed.status_code == 409


def test_idempotency_header_rejects_invalid_key(client, db):
    authenticate(db)
    result = client.post(
        "/resource/apply",
        headers={"Idempotency-Key": "bad key"},
        json={"pool_id": 1, "gpu_count": 1, "image_id": 1},
    )
    assert result.status_code == 422


def test_resource_summary_requires_authentication(client):
    assert client.get("/resource/summary").status_code == 401


def test_ordinary_user_resource_summary_does_not_double_count_overlapping_pools(client, db):
    from app.models import ResourcePool

    authenticate(db)
    db.add(ResourcePool(id=2, name="overlapping-pool", gpu_type_id=1, node_ids=[1]))
    db.commit()
    response = client.get("/resource/summary")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "total_gpus": 2, "free_gpus": 2, "used_gpus": 0, "unavailable_gpus": 0,
    }
    assert client.get("/cluster/nodes").status_code == 403


def test_resource_summary_separates_occupied_and_offline_capacity(client, db):
    from app.models import GPU, GPUStatus, Node, NodeStatus

    authenticate(db)
    db.get(Node, 1).status = NodeStatus.OFFLINE
    db.get(GPU, 1).status = GPUStatus.OCCUPIED
    db.commit()
    assert client.get("/resource/summary").json()["data"] == {
        "total_gpus": 2, "free_gpus": 0, "used_gpus": 1, "unavailable_gpus": 1,
    }
