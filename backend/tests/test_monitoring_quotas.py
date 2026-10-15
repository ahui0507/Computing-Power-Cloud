import asyncio
import hashlib
import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ResourceConflictError, InsufficientBalanceError
from app.models import (
    User,
    Node,
    NodeMetric,
    GPU,
    GPUStatus,
    Quota,
    OwnerType,
    Allocation,
    AllocationStatus,
)
from app.services.scheduler_service import SchedulerService
from app.services.k8s_service import K8sService
from app.services.resource_service import ResourceService
from app.services.quota_service import QuotaService
from app.services.telemetry_service import TelemetryService
from app.services.billing_service import BillingService


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(
        "app.routers.monitoring.pod_usage",
        lambda *args: {
            "state": "missing",
            "cpu_percent": None,
            "memory_percent": None,
            "restart_count": None,
            "last_exit_reason": None,
        },
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def cluster(monkeypatch):
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "pending"}))
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="pending"))


def apply(db, **kwargs):
    return asyncio.run(
        SchedulerService.create_allocation(
            db, user_id=1, pool_id=1, gpu_count=1, image_id=1, **kwargs
        )
    )


def promote(db):
    db.get(User, 1).role_id = 1
    db.commit()
    db.expire_all()


def quota(db, gpus=1, instances=1):
    db.add(
        Quota(
            owner_type=OwnerType.USER,
            owner_id=1,
            max_gpus=gpus,
            max_instances=instances,
            low_balance_amount=10,
            low_balance_minutes=30,
        )
    )
    db.commit()


def payload():
    return {
        "node_name": "worker-a",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "cpu_usage": 0,
        "mem_usage": 25,
        "cpu_cores": 24,
        "memory_total_mb": 131072,
        "memory_used_mb": 2048,
        "device_mapping_available": True,
        "gpus": [
            {
                "index": index,
                "uuid": f"GPU-test-{index}",
                "name": "Tesla K80",
                "utilization": 0,
                "memory_used_mb": 0,
                "memory_total_mb": 11441,
                "temperature": 30,
                "power_watts": None,
            }
            for index in (0, 1)
        ],
        "gpu_error": None,
    }


def token(db):
    value = "isolated-node-collector-key"
    db.get(Node, 1).monitor_token_hash = hashlib.sha256(value.encode()).hexdigest()
    db.commit()
    return {"Authorization": "Bearer " + value}


def test_quota_blocks_new_requests_but_replays_existing_identity(db, cluster):
    quota(db)
    first = apply(db, idempotency_key="original")
    assert apply(db, idempotency_key="original")["container_id"] == first["container_id"]
    with pytest.raises(ResourceConflictError, match="GPU 配额不足"):
        apply(db, idempotency_key="second")
    assert db.query(Allocation).count() == 1
    assert db.query(GPU).filter_by(status=GPUStatus.OCCUPIED).count() == 1


def test_instance_limit_is_independent_of_gpu_limit(db, cluster):
    quota(db, gpus=2, instances=1)
    apply(db)
    with pytest.raises(ResourceConflictError, match="实例配额不足"):
        apply(db)


def test_failed_cleanup_reservations_still_use_quota(db):
    quota(db)
    allocation = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        requested_gpu_count=1,
        gpu_type_id=1,
        node_id=1,
        pool_id=1,
        status=AllocationStatus.FAILED,
    )
    db.add(allocation)
    db.flush()
    gpu = db.get(GPU, 1)
    gpu.allocation_id = allocation.id
    gpu.occupied_by = 1
    gpu.status = GPUStatus.OCCUPIED
    db.commit()
    assert QuotaService.summary(db, 1)["remaining_gpus"] == 0
    ResourceService.release_gpus(db, allocation)
    assert QuotaService.summary(db, 1)["remaining_gpus"] == 1


def test_balance_guard_preserves_gpu_and_counts_all_pending_hourly_cost(db, cluster):
    db.get(User, 1).balance = Decimal("0.1000")
    db.commit()
    apply(db)
    with pytest.raises(InsufficientBalanceError):
        apply(db)
    assert db.query(Allocation).count() == 1
    assert db.query(GPU).filter_by(status=GPUStatus.FREE).count() == 1


def test_zero_balance_rejected_but_free_billing_mode_remains_usable(db, cluster, monkeypatch):
    db.get(User, 1).balance = 0
    db.commit()
    with pytest.raises(InsufficientBalanceError):
        apply(db)
    assert db.query(Allocation).count() == 0
    monkeypatch.setattr(settings, "BILLING_ENABLED", False)
    apply(db)
    assert QuotaService.summary(db, 1)["warning"] == "none"


def test_estimated_budget_uses_frozen_rate_cutoff_and_settlement_once(db):
    now = datetime(2026, 10, 10, 10)
    allocation = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        requested_gpu_count=2,
        gpu_type_id=1,
        hourly_price=6,
        start_time=now - timedelta(hours=1),
        ready_at=now - timedelta(hours=1),
        status=AllocationStatus.ACTIVE,
        container_id="budget-instance",
    )
    db.add(allocation)
    db.get(User, 1).balance = 20
    db.commit()
    result = QuotaService.summary(db, 1, now=now)
    assert result["unsettled_estimate"] == 12
    assert result["available_balance"] == 8
    assert result["estimated_remaining_minutes"] == 40
    assert result["warning"] == "low"
    allocation.billing_end_time = now - timedelta(minutes=30)
    db.commit()
    assert QuotaService.summary(db, 1, now=now)["unsettled_estimate"] == 6
    BillingService.settle_allocation(db, allocation, now)
    allocation.status = AllocationStatus.RELEASED
    db.commit()
    result = QuotaService.summary(db, 1, now=now)
    assert result["unsettled_estimate"] == 0
    assert result["available_balance"] == 14


def test_quota_edits_do_not_stop_existing_instances_and_can_restore_defaults(client, db, cluster):
    apply(db)
    assert client.post("/admin/quotas/1", json={"max_gpus": 0}).status_code == 403
    promote(db)
    result = client.post("/admin/quotas/1", json={"max_gpus": 0, "max_instances": 0})
    assert result.status_code == 200
    assert result.json()["data"]["used_instances"] == 1
    assert db.query(Allocation).one().status == AllocationStatus.APPROVED
    assert K8sService.delete_pod.call_count == 0
    with pytest.raises(ResourceConflictError):
        apply(db)
    restored = client.post("/admin/quotas/1", json={"inherited": True})
    assert restored.json()["data"]["inherited"] is True
    assert db.query(Quota).count() == 0


def test_budget_and_quota_endpoints_are_scoped(client, db, cluster):
    apply(db)
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    assert client.get("/resource/usage").json()["data"]["used_gpus"] == 0
    assert client.get("/admin/quotas/1").status_code == 403
    assert client.get("/resource/foreign-instance/metrics").status_code == 404


def test_collector_key_payload_replay_and_gpu_binding(client, db):
    headers = token(db)
    data = payload()
    assert client.post("/internal/telemetry", json=data).status_code == 401
    assert (
        client.post(
            "/internal/telemetry", json=data, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post("/internal/telemetry", json=data, headers=headers).json()["data"]["accepted"]
        is True
    )
    assert (
        client.post("/internal/telemetry", json=data, headers=headers).json()["data"]["accepted"]
        is False
    )
    assert db.query(NodeMetric).count() == 1
    data = payload()
    data["cpu_usage"] = 101
    assert client.post("/internal/telemetry", json=data, headers=headers).status_code == 422
    data = payload()
    data["gpus"][0]["index"] = 99
    assert client.post("/internal/telemetry", json=data, headers=headers).status_code == 409
    data = payload()
    data["collected_at"] = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    assert client.post("/internal/telemetry", json=data, headers=headers).status_code == 409
    assert db.query(NodeMetric).count() == 1


def test_missing_live_zero_partial_and_stale_are_distinct(client, db, monkeypatch):
    node = db.get(Node, 1)
    snapshot = TelemetryService.snapshot(db, node, detail=True)
    assert snapshot["telemetry_state"] == "missing" and snapshot["cpu_usage"] is None
    headers = token(db)
    client.post("/internal/telemetry", json=payload(), headers=headers)
    snapshot = TelemetryService.snapshot(db, node, detail=True)
    assert snapshot["telemetry_state"] == "live" and snapshot["cpu_usage"] == 0
    assert snapshot["gpu_list"][0]["utilization"] == 0
    assert snapshot["gpu_list"][0]["power_watts"] is None
    monkeypatch.setattr(settings, "TELEMETRY_ENFORCE_FRESHNESS", True)
    sample = db.query(NodeMetric).one()
    sample.received_at = datetime.utcnow() - timedelta(seconds=settings.TELEMETRY_STALE_SECONDS + 5)
    db.commit()
    snapshot = TelemetryService.snapshot(db, node, detail=True)
    assert snapshot["telemetry_state"] == "stale" and snapshot["cpu_usage"] is None
    assert snapshot["gpu_list"][0]["utilization"] is None
    assert ResourceService.get_summary(db)["free_gpus"] == 0
    data = payload()
    data["gpu_error"] = "driver unavailable"
    data["gpus"] = []
    client.post("/internal/telemetry", json=data, headers=headers)
    assert TelemetryService.snapshot(db, node)["telemetry_state"] == "partial"
    assert ResourceService.get_summary(db)["free_gpus"] == 0


def test_token_rotation_is_admin_only_and_key_hash_is_not_exposed(client, db):
    old = token(db)
    assert client.post("/admin/nodes/1/monitor-token").status_code == 403
    promote(db)
    response = client.post("/admin/nodes/1/monitor-token")
    assert response.status_code == 200
    new = response.json()["data"]["token"]
    assert client.post("/internal/telemetry", json=payload(), headers=old).status_code == 401
    assert (
        client.post(
            "/internal/telemetry",
            json=payload(),
            headers={"Authorization": "Bearer " + new},
        ).status_code
        == 200
    )
    detail = client.get("/cluster/node/1").text
    assert new not in detail and db.get(Node, 1).monitor_token_hash not in detail


def test_history_preserves_gaps_and_uses_average_or_peak_as_labelled(db):
    now = datetime(2026, 10, 10, 10)
    for seconds, cpu, memory in [(270, 0, 5), (269, 10, 8), (30, 80, 20)]:
        at = now - timedelta(seconds=seconds)
        db.add(
            NodeMetric(
                node_id=1,
                received_at=at,
                collected_at=at,
                cpu_usage=cpu,
                mem_usage=None,
                payload={
                    "gpus": [
                        {
                            "gpu_id": 1,
                            "utilization": cpu,
                            "memory_used_mb": memory,
                            "temperature": None,
                            "power_watts": None,
                        }
                    ]
                },
            )
        )
    db.commit()
    points = TelemetryService.history(db, 1, 5, now=now)["points"]
    assert len(points) == 20
    assert points[2]["cpu_usage"] == 5
    assert points[2]["gpus"][0]["memory_used_mb"] == 8
    assert points[3]["cpu_usage"] is None and points[3]["samples"] == 0
    assert points[2]["mem_usage"] is None


def test_monitor_retention_preserves_recent_samples(db):
    for days in [0, settings.TELEMETRY_RETENTION_DAYS + 1]:
        at = datetime.utcnow() - timedelta(days=days)
        db.add(NodeMetric(node_id=1, received_at=at, collected_at=at, payload={}))
    db.commit()
    assert TelemetryService.prune(db) == 1
    assert db.query(NodeMetric).count() == 1


def test_linux_collector_parses_real_units_and_unknowns():
    path = Path(__file__).resolve().parents[2] / "scripts/monitor_agent.py"
    spec = importlib.util.spec_from_file_location("monitor_agent", path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    before = agent.cpu_counters("cpu 100 0 50 800 50 0 0 0\n")
    after = agent.cpu_counters("cpu 150 0 50 900 100 0 0 0\n")
    assert agent.cpu_percent(before, after) == 25
    assert agent.cpu_percent(None, after) is None
    rows = agent.parse_gpus("0, GPU-test, Tesla K80, 0, 0, 11441, 30, [N/A]\n")
    assert rows[0]["utilization"] == 0 and rows[0]["memory_total_mb"] == 11441
    assert rows[0]["power_watts"] is None
    mapping = agent.parse_device_allocations(
        '{"Data":{"PodDeviceEntries":[{"ResourceName":"nvidia.com/gpu","PodUID":"pod-a","DeviceIDs":{"1":["GPU-test"]}}]}}'
    )
    assert mapping == {"GPU-test": ["pod-a"]}


def test_instance_metrics_use_actual_device_assignment_instead_of_reservation_index(
    client, db, monkeypatch
):
    allocation = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        requested_gpu_count=1,
        gpu_type_id=1,
        node_id=1,
        status=AllocationStatus.ACTIVE,
        container_id="actual-device",
        pod_name="actual-pod",
        gpu_ids=[1],
    )
    db.add(allocation)
    db.flush()
    db.get(GPU, 1).allocation_id = allocation.id
    db.get(GPU, 1).status = GPUStatus.OCCUPIED
    db.commit()
    data = payload()
    data["gpus"][1]["pod_uids"] = ["pod-uid"]
    data["gpus"][1]["memory_used_mb"] = 122
    monkeypatch.setattr(
        TelemetryService,
        "pod_owners",
        lambda *args: ({"pod-uid": allocation.id}, {"pod-uid"}),
    )
    assert client.post("/internal/telemetry", json=data, headers=token(db)).status_code == 200
    metrics = client.get("/resource/actual-device/metrics").json()["data"]
    assert len(metrics["gpu_list"]) == 1
    assert metrics["gpu_list"][0]["gpu_id"] == 2
    assert metrics["gpu_list"][0]["memory_used_mb"] == 122
    snapshot = TelemetryService.snapshot(db, db.get(Node, 1), detail=True)
    assert snapshot["gpu_list"][0]["status"] == "free"
    assert snapshot["gpu_list"][1]["status"] == "occupied"


def test_unavailable_device_mapping_cannot_expose_another_gpu_to_instance(client, db):
    allocation = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        requested_gpu_count=1,
        gpu_type_id=1,
        node_id=1,
        status=AllocationStatus.ACTIVE,
        container_id="unmapped",
        gpu_ids=[1],
    )
    db.add(allocation)
    db.commit()
    data = payload()
    data["device_mapping_available"] = False
    assert client.post("/internal/telemetry", json=data, headers=token(db)).status_code == 200
    metrics = client.get("/resource/unmapped/metrics").json()["data"]
    assert metrics["gpu_list"] == [] and metrics["telemetry_state"] == "partial"


def test_cpu_only_node_does_not_need_nvidia_driver(client, db):
    db.query(GPU).delete()
    db.commit()
    data = payload()
    data["gpus"] = []
    data["gpu_error"] = "driver unavailable"
    assert client.post("/internal/telemetry", json=data, headers=token(db)).status_code == 200
    assert TelemetryService.snapshot(db, db.get(Node, 1))["telemetry_state"] == "live"


def test_unmanaged_gpu_usage_is_visible_and_excluded_from_new_requests(client, db, monkeypatch):
    monkeypatch.setattr(settings, "TELEMETRY_ENFORCE_FRESHNESS", True)
    data = payload()
    data["gpus"][0]["memory_used_mb"] = 64
    assert client.post("/internal/telemetry", json=data, headers=token(db)).status_code == 200
    snapshot = TelemetryService.snapshot(db, db.get(Node, 1), detail=True)
    assert snapshot["gpu_list"][0]["status"] == "external"
    assert snapshot["schedulable"] is False
    assert ResourceService.get_summary(db)["free_gpus"] == 0
