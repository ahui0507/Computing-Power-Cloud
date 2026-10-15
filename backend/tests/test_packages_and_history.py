import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import re
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from sqlalchemy import text

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ClusterUnavailableError
from app.models import Allocation, AllocationStatus, AuditLog, BillingRecord, GPU, Image, Instance, InstanceStatus, Node, NodeMetric, User
from app.models.operation import AllocationOperation, OperationKind
from app.services.billing_service import BillingService
from app.services.debt_service import DebtService
from app.services.k8s_service import K8sService
from app.services.operation_service import OperationService
from app.services.package_service import PackageService
from app.services.quota_service import QuotaService


@pytest.fixture
def client(db, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    db.get(User, 1).balance = 2000
    db.commit()
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "running", "started_at": datetime.utcnow()}))
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="running"))
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def purchase(client, mode="day", count=1, key="package-one"):
    return client.post("/resource/apply", json={"pool_id": 1, "gpu_count": count, "image_id": 1, "billing_mode": mode},
                       headers={"Idempotency-Key": key})


@pytest.mark.parametrize("mode,count,amount,hours", [("day", 1, 96, 24), ("day", 2, 192, 24), ("week", 1, 504, 168), ("week", 2, 1008, 168)])
def test_package_purchase_replay_start_and_early_release(client, db, mode, count, amount, hours):
    first = purchase(client, mode, count)
    assert first.status_code == 200, first.json()
    row = db.query(Allocation).one()
    assert row.package_amount == amount and db.get(User, 1).balance == 2000 - amount
    assert row.package_expires_at - row.ready_at == timedelta(hours=hours)
    record = db.query(BillingRecord).one()
    assert record.amount == amount and record.billing_mode.value == mode
    assert purchase(client, mode, count).json()["data"]["container_id"] == row.container_id
    assert db.query(BillingRecord).count() == 1 and db.get(User, 1).balance == 2000 - amount
    assert QuotaService.summary(db, 1)["unsettled_estimate"] == 0
    assert QuotaService.summary(db, 1)["hourly_cost"] == 0
    for _ in range(2):
        assert client.post("/resource/release", json={"container_id": row.container_id}).status_code == 200
    assert record.amount == amount and row.package_refunded_at is None
    assert db.get(User, 1).balance == 2000 - amount
    assert all(gpu.allocation_id is None for gpu in db.query(GPU))


def test_insufficient_package_funds_roll_back_order_and_gpu(client, db):
    db.get(User, 1).balance = Decimal("95.9999")
    db.commit()
    response = purchase(client)
    assert response.status_code == 400
    assert db.query(Allocation).count() == db.query(BillingRecord).count() == 0
    assert db.get(User, 1).balance == Decimal("95.9999")
    assert all(gpu.allocation_id is None for gpu in db.query(GPU))


@pytest.mark.parametrize("confirmed", [False, True])
def test_creation_failure_refunds_exactly_once(client, db, monkeypatch, confirmed):
    error = ClusterUnavailableError()
    error.cleanup_confirmed = confirmed
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(side_effect=error))
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value=None))
    assert purchase(client).status_code == 503
    row = db.query(Allocation).one()
    assert row.package_refunded_at and row.package_expires_at is None
    assert db.get(User, 1).balance == 2000
    assert db.query(BillingRecord).one().amount == 0
    assert purchase(client).status_code == 503
    assert db.get(User, 1).balance == 2000
    assert db.query(AuditLog).filter_by(action="包时创建失败退还余额").count() == 1
    assert all(gpu.allocation_id is None for gpu in db.query(GPU))


def test_package_expiry_persists_and_queues_one_release(client, db):
    assert purchase(client).status_code == 200
    row = db.query(Allocation).one()
    now = datetime.utcnow()
    row.ready_at = row.start_time = row.instance.started_at = now - timedelta(hours=25)
    row.package_expires_at = row.ready_at + timedelta(hours=24)
    record = db.query(BillingRecord).one()
    record.start_time, record.end_time = row.ready_at, row.package_expires_at
    db.commit()
    PackageService.expire(db, now)
    cutoff = row.package_expires_at
    PackageService.expire(db, now + timedelta(hours=1))
    assert row.status == AllocationStatus.RELEASING and row.billing_end_time == cutoff
    assert db.query(AllocationOperation).filter_by(kind=OperationKind.RELEASE).count() == 1
    asyncio.run(OperationService.execute_release(db, row.id))
    assert row.status == AllocationStatus.RELEASED
    assert record.amount == 96 and record.end_time == cutoff
    assert db.get(User, 1).balance == 1904


def test_package_saving_image_defers_cleanup_but_keeps_original_deadline(client, db):
    purchase(client)
    row = db.query(Allocation).one()
    row.package_expires_at = datetime.utcnow() - timedelta(seconds=1)
    image = Image(name="snapshot-test", tag="v1", visibility="private", owner_id=1, snapshot_status="saving", source_container_id=row.container_id)
    db.add(image)
    db.commit()
    deadline = row.package_expires_at
    PackageService.expire(db)
    assert row.status == AllocationStatus.ACTIVE and row.package_expires_at == deadline
    image.snapshot_status = "failed"
    db.commit()
    PackageService.expire(db)
    assert row.status == AllocationStatus.RELEASING and row.billing_end_time == deadline


def test_debt_recovery_only_releases_unpaid_hourly_instances(client, db):
    purchase(client)
    prepaid = db.query(Allocation).one()
    hourly = purchase(client, "on_demand", key="hourly-extra")
    assert hourly.status_code == 200
    row = db.query(Allocation).filter(Allocation.id != prepaid.id).one()
    old = datetime.utcnow() - timedelta(hours=8)
    row.start_time = row.instance.started_at = row.ready_at = old
    db.get(User, 1).balance = 0
    db.commit()
    asyncio.run(DebtService.run_once(db))
    assert row.status == AllocationStatus.RELEASING
    assert prepaid.status == AllocationStatus.ACTIVE


def test_readable_names_are_unique_and_billing_keeps_route_identifier(client, db):
    for key in ("one", "two"):
        assert purchase(client, "on_demand", key=key).status_code == 200
    rows = db.query(Allocation).order_by(Allocation.id).all()
    names = [row.instance.instance_name for row in rows]
    assert len(set(names)) == 2 and all(re.fullmatch(r"K80-\d{10}(-\d+)?", name) for name in names)
    for row in rows:
        client.post("/resource/release", json={"container_id": row.container_id})
    records = client.get("/billing/records").json()["data"]
    assert {record["container_id"] for record in records} == {row.container_id for row in rows}
    assert {record["instance_name"] for record in records} == set(names)


def test_history_is_owner_limited_but_admin_can_read_all(client, db):
    for owner in (1, 2):
        for index in range(16):
            row = Allocation(request_id=f"history-{owner}-{index}", user_id=owner, node_id=1, pool_id=1,
                image_id=1, gpu_type_id=1, requested_gpu_count=1, status=AllocationStatus.RELEASED,
                container_id=f"history-{owner}-{index}", created_at=datetime(2026, 10, 10) + timedelta(minutes=index))
            db.add(row)
    db.commit()
    ordinary = client.get("/resource/history?user_id=2&limit=10000").json()["data"]
    assert len(ordinary) == 10 and all(item["container_id"].startswith("history-1-") for item in ordinary)
    assert ordinary[0]["container_id"] == "history-1-15"
    assert len(client.get("/resource/my").json()["data"]) == 10
    db.get(User, 2).role_id = 1
    db.commit()
    db.expire_all()
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    admin = client.get("/resource/history").json()["data"]
    assert len(admin) == 32
    assert {item["user_email"] for item in admin} == {"owner@example.com", "other@example.com"}


def test_market_reports_driver_and_separate_cuda_limits(client, db):
    db.get(Node, 1).labels = {"platform.driver_version": "470.256.02", "platform.driver_cuda_max": "11.4"}
    db.add(NodeMetric(node_id=1, collected_at=datetime.utcnow(), received_at=datetime.utcnow(),
                      payload={"gpus": [{"gpu_id": 1, "memory_total_mb": 11441}]}))
    db.commit()
    pool = client.get("/resource/pools").json()["data"][0]
    assert pool["driver_versions"] == ["470.256.02"]
    assert pool["memory_mb"] == 11441
    assert pool["driver_cuda_versions"] == ["11.4"] and pool["cuda_arch_max"] == "11.8"
    assert (pool["hourly_price"], pool["daily_price"], pool["weekly_price"]) == (5, 96, 504)


def test_administrator_history_reads_legacy_hourly_bill_without_changing_amount(client, db):
    row = Allocation(request_id="legacy-bill", user_id=2, node_id=1, pool_id=1, image_id=1,
                     gpu_type_id=1, requested_gpu_count=1, status=AllocationStatus.RELEASED, container_id="legacy-order")
    db.add(row)
    db.flush()
    record = BillingRecord(allocation_id=row.id, user_id=2, gpu_type_id=1, gpu_count=1,
                           start_time=datetime.utcnow(), end_time=datetime.utcnow(), minutes=1,
                           unit_price=5, amount=Decimal('1.2345'), billing_mode="hour", settled=True)
    db.add(record)
    db.commit()
    db.execute(text("UPDATE billing_records SET billing_mode='on_demand' WHERE id=:id"), {"id": record.id})
    db.get(User, 1).role_id = 1
    db.commit()
    db.expire_all()
    response = client.get('/resource/history')
    assert response.status_code == 200
    assert response.json()['data'][0]['settled_amount'] == 1.2345
    assert db.get(BillingRecord, record.id).amount == Decimal('1.2345')
