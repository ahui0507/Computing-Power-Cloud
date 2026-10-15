import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import (
    AuthorizationError,
    ClusterOperationError,
    ClusterUnavailableError,
    InsufficientResourceError,
    OperationNotSupportedError,
    ResourceConflictError,
)
from app.models import Allocation, AllocationStatus, GPU, GPUStatus, InstanceStatus
from app.services.container_service import ContainerService
from app.services.instance_service import InstanceService
from app.services.k8s_service import K8sService
from app.services.resource_service import ResourceService
from app.services.scheduler_service import SchedulerService


@pytest.fixture
def cluster(monkeypatch):
    create = AsyncMock(
        return_value={"status": "pending", "jupyter_url": "http://platform/jupyter/1/"}
    )
    delete = AsyncMock()
    monkeypatch.setattr(K8sService, "create_pod", create)
    monkeypatch.setattr(K8sService, "delete_pod", delete)
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="pending"))
    return create, delete


def apply(db, **overrides):
    kwargs = dict(user_id=1, pool_id=1, gpu_count=1, image_id=1)
    kwargs.update(overrides)
    return asyncio.run(SchedulerService.create_allocation(db, **kwargs))


def test_submitted_pod_is_pending_until_ready(db, cluster, monkeypatch):
    result = apply(db)
    allocation = db.query(Allocation).one()
    assert result["status"] == "pending"
    assert result["jupyter_url"] is None
    assert allocation.start_time is None
    assert allocation.instance.status == InstanceStatus.CREATING
    assert cluster[0].call_args.kwargs["node_name"] == "worker-a"
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="running"))
    responses = asyncio.run(InstanceService.get_user_instances(db, 1, refresh=True))
    assert responses[0].status == "running"
    assert responses[0].start_time is not None
    assert responses[0].jupyter_url is not None
    assert allocation.instance.status == InstanceStatus.RUNNING


def test_unavailable_cluster_does_not_create_fake_running_instance(db, cluster):
    cluster[0].side_effect = ClusterUnavailableError()
    with pytest.raises(ClusterUnavailableError):
        apply(db)
    allocation = db.query(Allocation).one()
    assert allocation.status == AllocationStatus.FAILED
    assert allocation.instance.status == InstanceStatus.ERROR
    assert all(gpu.status == GPUStatus.FREE and gpu.allocation_id is None for gpu in db.query(GPU))


def test_unconfirmed_cleanup_keeps_gpu_reservation(db, cluster):
    cluster[0].side_effect = ClusterOperationError("creation failed")
    cluster[1].side_effect = ClusterOperationError("deletion failed")
    with pytest.raises(ClusterOperationError):
        apply(db)
    allocation = db.query(Allocation).one()
    assert allocation.status == AllocationStatus.FAILED
    assert db.get(GPU, 1).allocation_id == allocation.id
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED
    cluster[1].side_effect = None
    asyncio.run(SchedulerService.release_allocation(db, 1, allocation.container_id))
    assert db.get(GPU, 1).status == GPUStatus.FREE


def test_error_result_from_old_adapter_is_rejected(db, cluster):
    cluster[0].return_value = {"error": "cluster is unavailable"}
    with pytest.raises(ClusterOperationError):
        apply(db)
    assert db.query(Allocation).one().status == AllocationStatus.FAILED
    assert db.get(GPU, 1).status == GPUStatus.FREE


def test_failed_deletion_does_not_release_gpu(db, cluster):
    result = apply(db)
    cluster[1].side_effect = ClusterOperationError("deletion timed out")
    with pytest.raises(ClusterOperationError):
        asyncio.run(SchedulerService.release_allocation(db, 1, result["container_id"]))
    assert db.query(Allocation).one().status == AllocationStatus.RELEASING
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_repeated_release_cannot_free_new_owners_gpu(db, cluster):
    first = apply(db)
    old = db.query(Allocation).one()
    asyncio.run(SchedulerService.release_allocation(db, 1, first["container_id"]))
    second = apply(db)
    new = db.query(Allocation).filter(Allocation.container_id == second["container_id"]).one()
    asyncio.run(SchedulerService.release_allocation(db, 1, first["container_id"]))
    ResourceService.release_gpus(db, old)
    db.commit()
    assert db.get(GPU, 1).allocation_id == new.id
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_reservation_rollback_does_not_leave_partial_allocation(db, cluster, monkeypatch):
    commit = db.commit
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db failed")))
    with pytest.raises(RuntimeError):
        apply(db)
    monkeypatch.setattr(db, "commit", commit)
    assert db.query(Allocation).count() == 0
    assert all(gpu.status == GPUStatus.FREE for gpu in db.query(GPU))
    cluster[0].assert_not_called()


def test_insufficient_capacity_never_calls_cluster(db, cluster):
    apply(db, gpu_count=2)
    with pytest.raises(InsufficientResourceError):
        apply(db)
    assert cluster[0].call_count == 1


def test_other_users_private_image_is_rejected(db, cluster):
    with pytest.raises(AuthorizationError):
        apply(db, image_id=2)
    assert db.query(Allocation).count() == 0
    cluster[0].assert_not_called()


def test_unsupported_pause_does_not_change_instance_state(db, cluster):
    result = apply(db)
    allocation = db.query(Allocation).one()
    with pytest.raises(OperationNotSupportedError):
        asyncio.run(ContainerService.stop_container(db, 1, result["container_id"]))
    assert allocation.status == AllocationStatus.APPROVED
    assert allocation.instance.status == InstanceStatus.CREATING
    cluster[1].assert_not_called()


def test_state_refresh_does_not_revive_concurrently_released_allocation(db, cluster, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    result = apply(db)

    async def release_during_snapshot(pod_name, **kwargs):
        other = sessionmaker(bind=db.get_bind(), expire_on_commit=False)()
        try:
            allocation = (
                other.query(Allocation)
                .filter(Allocation.container_id == result["container_id"])
                .one()
            )
            allocation.status = AllocationStatus.RELEASED
            allocation.instance.status = InstanceStatus.TERMINATED
            other.commit()
        finally:
            other.close()
        return "running"

    monkeypatch.setattr(K8sService, "get_pod_status", release_during_snapshot)
    responses = asyncio.run(InstanceService.get_user_instances(db, 1, refresh=True))
    assert responses[0].status == "released"
    assert responses[0].jupyter_url is None


def test_release_is_blocked_while_cluster_creation_is_in_flight(db, cluster, monkeypatch):
    async def create_while_release_is_attempted(**kwargs):
        allocation = kwargs["allocation"]
        assert allocation.status == AllocationStatus.PENDING
        with pytest.raises(ResourceConflictError):
            await SchedulerService.release_allocation(db, 1, allocation.container_id)
        return {"status": "pending"}

    monkeypatch.setattr(K8sService, "create_pod", create_while_release_is_attempted)
    result = apply(db)
    assert result["status"] == "pending"
    cluster[1].assert_not_called()
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_nodeport_access_also_requires_an_instance_token(db, cluster, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "INGRESS_ENABLED", False)
    monkeypatch.setattr(settings, "CONTROL_NODE_ID", None)
    cluster[0].return_value = {"status": "running", "jupyter_port": 30456}
    result = apply(db)
    assert result["jupyter_url"].startswith("http://192.0.2.1:30456/?token=")
    listing = InstanceService.to_response(db, db.query(Allocation).one())
    assert listing.jupyter_url == result["jupyter_url"]
