import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import (
    User,
    Image,
    Allocation,
    AllocationStatus,
    BalanceCredit,
    Payment,
    Instance,
    InstanceStatus,
)
from app.models.operation import AllocationOperation, OperationKind
from app.services.debt_service import DebtService
from app.services.image_service import ImageService
from app.services.quota_service import QuotaService
from app.services.worker_agent_client import WorkerAgentClient
from app.infrastructure.kubernetes.manifests import build_pod, build_service, build_auth_secret
from test_kubernetes_gateway import spec


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def active(db, start, rate=5):
    row = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        pool_id=1,
        image_id=1,
        node_id=1,
        requested_gpu_count=1,
        gpu_type_id=1,
        hourly_price=rate,
        status=AllocationStatus.ACTIVE,
        container_id="campus-" + uuid4().hex,
        pod_name="pod-1-test",
        start_time=start,
        ready_at=start,
    )
    db.add(row)
    db.commit()
    return row


def test_self_recharge_channel_disabled_even_for_admin(client, db):
    for role in (2, 1):
        db.get(User, 1).role_id = role
        db.commit()
        db.expire_all()
        assert client.post("/billing/recharge", json={"amount": 1000}).status_code == 403
    assert db.get(User, 1).balance == 100
    assert db.query(Payment).count() == db.query(BalanceCredit).count() == 0
    assert client.get("/platform/capabilities").json()["data"]["recharge_mode"] == "admin_only"


def test_exact_ten_yuan_warning(client, db):
    db.get(User, 1).balance = Decimal("10.0001")
    db.commit()
    assert QuotaService.summary(db, 1)["warning"] == "none"
    db.get(User, 1).balance = Decimal("10")
    db.commit()
    assert QuotaService.summary(db, 1)["warning"] == "low"


def test_zero_price_workload_does_not_start_debt_release_timer(db):
    now = datetime(2026, 10, 10, 12)
    row = active(db, now - timedelta(hours=24), rate=0)
    user = db.get(User, 1)
    user.balance = 0
    db.commit()
    asyncio.run(DebtService.run_once(db, now))
    assert user.grace_expires_at is None
    assert row.status == AllocationStatus.ACTIVE


def test_image_availability_ignores_untagged_cache_entries(client, monkeypatch):
    from app.infrastructure.kubernetes import client as kubernetes_client

    core, network = MagicMock(), MagicMock()
    core.list_node.return_value.items = [
        SimpleNamespace(
            metadata=SimpleNamespace(name="worker-a"),
            status=SimpleNamespace(
                images=[
                    SimpleNamespace(names=None),
                    SimpleNamespace(names=["docker.io/library/test-jupyter:v1"]),
                ]
            ),
        )
    ]
    monkeypatch.setattr(kubernetes_client, "create_clients", lambda: (core, network))
    response = client.get("/images/availability")
    assert response.status_code == 200
    assert response.json()["data"]["1"] == [1]


def test_grace_starts_at_depletion_and_is_persisted(db):
    now = datetime(2026, 10, 10, 12)
    row = active(db, now - timedelta(hours=2))
    user = db.get(User, 1)
    user.balance = 5
    db.commit()
    asyncio.run(DebtService.run_once(db, now))
    assert user.debt_started_at == now - timedelta(hours=1)
    assert user.grace_expires_at == now + timedelta(hours=5)
    asyncio.run(DebtService.run_once(db, now + timedelta(hours=4)))
    assert user.grace_expires_at == now + timedelta(hours=5)
    assert row.status == AllocationStatus.ACTIVE
    assert db.query(AllocationOperation).count() == 0


def test_grace_expiry_queues_release_once_and_freezes_billing_cutoff(db):
    now = datetime(2026, 10, 10, 12)
    row = active(db, now - timedelta(hours=8))
    user = db.get(User, 1)
    user.balance = 5
    db.commit()
    asyncio.run(DebtService.run_once(db, now))
    assert row.status == AllocationStatus.RELEASING
    assert row.billing_end_time == now - timedelta(hours=1)
    operation = db.query(AllocationOperation).one()
    assert operation.kind == OperationKind.RELEASE
    asyncio.run(DebtService.run_once(db, now + timedelta(hours=1)))
    assert db.query(AllocationOperation).count() == 1
    assert row.billing_end_time == now - timedelta(hours=1)


def test_credit_clears_grace_only_when_available_budget_positive(db):
    now = datetime(2026, 10, 10, 12)
    active(db, now - timedelta(hours=2))
    user = db.get(User, 1)
    user.balance = 5
    db.commit()
    DebtService.update_locked_user(db, user, now)
    db.commit()
    deadline = user.grace_expires_at
    user.balance = 9
    DebtService.update_locked_user(db, user, now)
    assert user.grace_expires_at == deadline
    user.balance = 11
    DebtService.update_locked_user(db, user, now)
    assert user.grace_expires_at is None and user.debt_started_at is None


def test_multiple_instances_released_on_same_deadline(db):
    now = datetime(2026, 10, 10, 12)
    rows = [active(db, now - timedelta(hours=8)) for _ in range(2)]
    user = db.get(User, 1)
    user.balance = 5
    db.commit()
    asyncio.run(DebtService.run_once(db, now))
    assert all(row.status == AllocationStatus.RELEASING for row in rows)
    assert rows[0].billing_end_time == rows[1].billing_end_time


def test_staggered_start_times_recover_actual_depletion_instead_of_current_rate(db):
    now = datetime(2026, 10, 10, 12)
    active(db, now - timedelta(hours=8))
    active(db, now - timedelta(hours=1))
    user = db.get(User, 1)
    user.balance = 5
    db.commit()
    DebtService.update_locked_user(db, user, now)
    assert user.debt_started_at == now - timedelta(hours=7)
    assert user.grace_expires_at == now - timedelta(hours=1)


def test_snapshot_task_persists_replays_checks_owner_and_prevents_early_release(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "WORKER_AGENT_TOKEN", "isolated-worker-agent-token")
    call = MagicMock(return_value={"status": "saving"})
    monkeypatch.setattr(WorkerAgentClient, "request", call)
    row = active(db, datetime.utcnow())
    body = {
        "container_id": row.container_id,
        "name": "project",
        "tag": "v1",
        "request_id": str(uuid4()),
    }
    first = client.post("/images/save", json=body)
    assert first.status_code == 200
    image_id = first.json()["data"]["image_id"]
    assert client.post("/images/save", json=body).json()["data"]["image_id"] == image_id
    assert db.query(Image).filter_by(snapshot_status="saving").count() == 1
    assert (
        client.post("/resource/release", json={"container_id": row.container_id}).status_code == 409
    )
    assert client.post("/images/delete", json={"id": image_id}).status_code == 409
    assert client.post("/images/save", json={**body, "tag": "v2"}).status_code == 409
    assert client.post("/images/save", json={**body, "request_id": str(uuid4())}).status_code == 409
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.post("/images/save", json={**body, "request_id": str(uuid4())}).status_code == 404
    assert all(item["image_id"] != image_id for item in client.get("/images/my").json()["data"])
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    call.return_value = {"status": "ready", "size_bytes": 1024**3}
    ImageService.reconcile_saves(db)
    assert db.get(Image, image_id).snapshot_status == "ready"
    assert client.get("/images/my").json()["data"][0]["is_snapshot"]


def test_failed_snapshot_not_usable_and_ssh_and_storage_respect_ownership(client, db, monkeypatch):
    row = active(db, datetime.utcnow())
    assert client.post("/resource/" + row.container_id + "/ssh").status_code == 409
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.post("/resource/" + row.container_id + "/ssh").status_code == 404
    info = client.get("/storage/info").json()["data"]
    assert info["instance_path"] == "/data" and info["server_path"].endswith("user_2")
    assert info["shared_across_instances"] and info["retained_after_release"]


def test_personal_image_delete_is_recoverable_and_cleans_history_reference(client, db, monkeypatch):
    image = Image(
        name="platform.local/user-1/test",
        tag="v1",
        owner_id=1,
        visibility="private",
        snapshot_id=str(uuid4()),
        source_node_id=1,
        snapshot_status="ready",
    )
    db.add(image)
    db.commit()
    image_id = image.id
    row = active(db, datetime.utcnow())
    row.image_id = image_id
    db.commit()
    instance = Instance(
        allocation_id=row.id,
        instance_name=row.container_id,
        node_id=1,
        gpu_ids=[1],
        image_id=image_id,
        status=InstanceStatus.RUNNING,
    )
    db.add(instance)
    db.commit()
    assert client.post("/images/delete", json={"id": image_id}).status_code == 409
    row.status = AllocationStatus.RELEASED
    db.commit()
    assert client.post("/images/delete", json={"id": image_id}).status_code == 200
    assert image.snapshot_status == "deleting"
    failing = MagicMock(side_effect=OSError("agent unavailable"))
    monkeypatch.setattr(WorkerAgentClient, "request", failing)
    ImageService.reconcile_saves(db)
    assert db.get(Image, image_id).snapshot_status == "deleting"
    monkeypatch.setattr(WorkerAgentClient, "request", MagicMock(return_value={"status": "deleted"}))
    ImageService.reconcile_saves(db)
    assert db.get(Image, image_id) is None
    db.refresh(row)
    assert row.image_id is None
    db.refresh(instance)
    assert instance.image_id is None and instance.instance_name == row.container_id


def test_ssh_template_separates_ephemeral_keys_from_saved_system_disk():
    workload = replace(spec(), ssh_enabled=True, ssh_authorized_keys="ssh-ed25519 test-key")
    pod = build_pod(workload)
    assert pod["spec"]["containers"][0]["command"][:2] == ["/bin/bash", "-c"]
    assert build_service(workload)["spec"]["type"] == "NodePort"
    volumes = {item["name"]: item for item in pod["spec"]["volumes"]}
    assert "emptyDir" in volumes["platform-ssh"] and "secret" in volumes["platform-auth"]
    assert "authorized_keys" in build_auth_secret(workload)["data"]
    assert "test-key" not in str(pod)
