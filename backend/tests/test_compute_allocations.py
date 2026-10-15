import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from kubernetes import client as kubernetes_client
from kubernetes.client.exceptions import ApiException

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ClusterOperationError, ClusterUnavailableError
from app.main import app
from app.models import Allocation, GPU, GPUStatus, GPUType, Node, ResourcePool, User
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.manifests import build_pod
from app.services.compute_budget_service import ComputeBudgetService
from app.services.k8s_service import K8sService
from app.services.operation_service import OperationService
from app.services.resource_service import ResourceService
from test_kubernetes_gateway import spec


@pytest.fixture
def client(db, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    for user in db.query(User):
        user.balance = 2000
    for index in (3, 4):
        db.add(GPU(id=index, node_id=1, gpu_index=index - 1, gpu_type_id=1, status=GPUStatus.FREE))
    db.commit()
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "running"}))
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="running"))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def apply(client, cards=1, key="compute", mode="on_demand"):
    return client.post("/resource/apply", json={"pool_id": 1, "gpu_count": cards, "image_id": 1, "billing_mode": mode},
                       headers={"Idempotency-Key": key})


@pytest.mark.parametrize("cards", [1, 2, 4])
def test_compute_configuration_is_frozen_reserved_and_released_with_gpu(client, db, cards, monkeypatch):
    expected_cpu, expected_ram = ComputeBudgetService.quote(ComputeBudgetService.node_budget(db, db.get(Node, 1)), cards)
    response = apply(client, cards)
    assert response.status_code == 200, response.json()
    row = db.query(Allocation).one()
    assert (row.cpu_millicores, row.ram_mb, row.compute_reserved) == (expected_cpu, expected_ram, True)
    assert row.node_gpu_count == 4 and row.cpu_cores is None
    created = OperationService.get(db, row.id, "create")
    assert created.payload["options"]["cpu_millicores"] == expected_cpu
    assert created.payload["options"]["ram_mb"] == expected_ram
    assert client.get("/resource/my").json()["data"][0]["cpu_cores"] == expected_cpu / 1000
    assert apply(client, cards).json()["data"]["container_id"] == row.container_id
    assert db.query(Allocation).count() == 1
    monkeypatch.setattr(settings, "NODE_RESERVED_CPU_PERCENT", 30)
    assert row.cpu_millicores == expected_cpu and created.payload["options"]["cpu_millicores"] == expected_cpu
    assert client.post("/resource/release", json={"container_id": row.container_id}).status_code == 200
    assert not row.compute_reserved
    budget = ComputeBudgetService.node_budget(db, db.get(Node, 1))
    assert budget["reserved_cpu_cores"] == budget["reserved_ram_mb"] == 0
    assert all(gpu.allocation_id is None for gpu in db.query(GPU))


@pytest.mark.parametrize("bottleneck", ["cpu", "ram"])
def test_cpu_or_ram_shortage_rejects_before_order_payment_or_gpu_reservation(client, db, bottleneck):
    budget = ComputeBudgetService.node_budget(db, db.get(Node, 1))
    unit_cpu, unit_ram = ComputeBudgetService.quote(budget, 1)
    old = Allocation(request_id="larger-old-quota", user_id=2, node_id=1, requested_gpu_count=1,
        gpu_type_id=1, hourly_price=5,
        compute_reserved=True, status="active",
        cpu_millicores=budget["capacity_cpu_millicores"] - unit_cpu if bottleneck == "cpu" else 1,
        ram_mb=budget["capacity_ram_mb"] - unit_ram if bottleneck == "ram" else 1)
    db.add(old)
    db.commit()
    pool = client.get("/resource/pools").json()["data"][0]
    assert pool["physical_free_gpus"] == 4 and pool["free_gpus"] == pool["max_gpus_per_instance"] == 1
    before = db.get(User, 1).balance
    refused = apply(client, 2, mode="day")
    assert refused.status_code == 400 and "CPU/内存" in str(refused.json())
    assert db.query(Allocation).count() == 1 and db.get(User, 1).balance == before
    assert all(gpu.status == GPUStatus.FREE for gpu in db.query(GPU))
    assert client.get("/resource/summary").json()["data"]["free_gpus"] == 1


def test_node_capacity_is_shared_across_users_and_gpu_pools(client, db):
    db.add(GPUType(id=2, code="V100", name="V100"))
    db.add(ResourcePool(id=2, name="other pool", gpu_type_id=2, node_ids=[1]))
    db.add(GPU(id=5, node_id=1, gpu_index=4, gpu_type_id=2, status=GPUStatus.FREE))
    db.commit()
    budget = ComputeBudgetService.node_budget(db, db.get(Node, 1))
    unit_cpu, _ = ComputeBudgetService.quote(budget, 1)
    db.add(Allocation(request_id="other-cpu-reservation", user_id=2, node_id=1, requested_gpu_count=1,
        gpu_type_id=1, hourly_price=5,
        compute_reserved=True, status="active", cpu_millicores=budget["capacity_cpu_millicores"] - unit_cpu, ram_mb=1))
    db.commit()
    assert apply(client).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 2)
    reply = client.post("/resource/apply", json={"pool_id": 2, "gpu_count": 1, "image_id": 1})
    assert reply.status_code == 400 and "CPU/内存" in str(reply.json())
    assert db.query(Allocation).count() == 2 and db.get(GPU, 5).status == GPUStatus.FREE
    assert all(pool["free_gpus"] == 0 for pool in client.get("/resource/pools").json()["data"])


def test_release_failure_keeps_compute_reserved_until_cleanup_is_confirmed(client, db, monkeypatch):
    assert apply(client, 4).status_code == 200
    row = db.query(Allocation).one()
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock(side_effect=ClusterUnavailableError()))
    reply = client.post("/resource/release", json={"container_id": row.container_id})
    assert reply.status_code == 503
    db.refresh(row)
    assert row.status.value == "releasing"
    assert row.compute_reserved
    assert ComputeBudgetService.node_budget(db, db.get(Node, 1))["available_cpu_cores"] == 0
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    assert client.post("/resource/release", json={"container_id": row.container_id}).status_code == 200
    assert not row.compute_reserved
    assert ResourceService._calculate_free_gpus(db, db.get(ResourcePool, 1)) == 4
    assert db.get(ResourcePool, 1).free_gpus == 4


def test_creation_failure_and_repeated_old_release_do_not_leak_or_free_new_compute(client, db, monkeypatch):
    error = ClusterUnavailableError()
    error.cleanup_confirmed = True
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(side_effect=error))
    assert apply(client, key="failed").status_code == 503
    old = db.query(Allocation).one()
    assert not old.compute_reserved
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "running"}))
    assert apply(client, key="new").status_code == 200
    new = db.query(Allocation).filter(Allocation.id != old.id).one()
    ResourceService.release_gpus(db, old)
    db.commit()
    assert new.compute_reserved
    budget = ComputeBudgetService.node_budget(db, db.get(Node, 1))
    expected_cpu, expected_ram = ComputeBudgetService.quote(budget, 1)
    assert budget["reserved_cpu_millicores"] == expected_cpu and budget["reserved_ram_mb"] == expected_ram


def test_legacy_unbounded_or_unknown_capacity_fails_closed(client, db):
    legacy = Allocation(request_id="legacy", user_id=2, node_id=1, requested_gpu_count=1,
                        compute_reserved=True, status="active")
    db.add(legacy)
    db.commit()
    assert apply(client).status_code == 400
    legacy.compute_reserved = False
    db.get(Node, 1).memory_gb = 0
    db.commit()
    assert apply(client).status_code == 400
    assert db.query(Allocation).count() == 1


def test_uncleaned_cpu_reservation_is_visible_even_without_gpu_record(client, db):
    from app.services.quota_service import QuotaService
    row = Allocation(request_id="uncleaned", user_id=1, node_id=1, requested_gpu_count=1,
        cpu_cores=4, ram_mb=24576, compute_reserved=True, status="failed")
    db.add(row)
    db.commit()
    usage = QuotaService.summary(db, 1)
    assert usage["used_cpu_cores"] == 4 and usage["used_ram_mb"] == 24576
    ResourceService.release_gpus(db, row)
    db.commit()
    assert QuotaService.summary(db, 1)["used_cpu_cores"] == 0


@pytest.mark.parametrize("cards", [1, 2, 4])
def test_kubernetes_requests_and_limits_match_frozen_allocation(cards):
    workload = replace(spec(), gpu_count=cards, cpu_millicores=4800 * cards, ram_mb=26214 * cards)
    manifest = build_pod(workload)
    expected = {"nvidia.com/gpu": str(cards), "cpu": f"{4800 * cards}m", "memory": f"{26214 * cards}Mi"}
    assert manifest["spec"]["containers"][0]["resources"] == {"requests": expected, "limits": expected}
    pod = kubernetes_client.ApiClient()._ApiClient__deserialize(manifest, "V1Pod")
    create = MagicMock(side_effect=ApiException(status=409))
    read = MagicMock(return_value=pod)
    gateway = KubernetesGateway(MagicMock(), MagicMock())
    assert gateway._ensure(create, read, manifest, workload, "pod") is pod
    pod.spec.containers[0].resources.limits["cpu"] = "1"
    with pytest.raises(ClusterOperationError, match="CPU/内存配额"):
        gateway._ensure(create, read, manifest, workload, "pod")


def test_proportions_follow_each_nodes_hardware_and_gpu_count(client, db):
    first = ComputeBudgetService.node_budget(db, db.get(Node, 1))
    assert ComputeBudgetService.quote(first, 1)[0] == 4800
    db.add(Node(id=2, hostname="worker-b", ip="10.0.0.2", cpu_cores=32, memory_gb=96, status="online"))
    db.add_all([GPU(id=index, node_id=2, gpu_index=index - 5, gpu_type_id=1, status=GPUStatus.FREE) for index in (5, 6)])
    pool = db.get(ResourcePool, 1)
    pool.node_ids = [1, 2]
    db.commit()
    second = ComputeBudgetService.node_budget(db, db.get(Node, 2))
    assert ComputeBudgetService.quote(second, 1)[0] == 12800
    assert client.get("/resource/pools").json()["data"][0]["node_gpu_count"] is None
    assert apply(client).status_code == 200
    assert db.query(Allocation).one().node_gpu_count == 4


def test_integer_rounding_never_oversells_a_remaining_budget():
    budget = {"node_gpu_count": 3, "capacity_cpu_millicores": 10, "capacity_ram_mb": 11,
              "available_cpu_millicores": 6, "available_ram_mb": 6}
    assert ComputeBudgetService.quote(budget, 2) == (6, 7)
    assert ComputeBudgetService.available_cards(budget) == 1
    single = ComputeBudgetService.quote(budget, 1)
    assert single[0] * 3 <= 10 and single[1] * 3 <= 11
    too_small = {**budget, "node_gpu_count": 4, "capacity_cpu_millicores": 2}
    assert ComputeBudgetService.available_cards(too_small) == 0
