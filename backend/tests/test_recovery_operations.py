import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ClusterOperationError, ResourceConflictError
from app.models import Allocation, AllocationStatus, BillingRecord, GPU, GPUStatus, User, Instance
from app.models.operation import AllocationOperation, OperationKind, OperationStatus
from app.services import operation_service, reconciliation_service
from app.services.operation_service import OperationService
from app.services.reconciliation_service import ReconciliationService
from app.services.scheduler_service import SchedulerService
from app.services.instance_service import InstanceService
from app.services.k8s_service import K8sService
from app.infrastructure.kubernetes.status import PodStatus


@pytest.fixture
def cluster(monkeypatch):
    create = AsyncMock(return_value={"status": "pending"})
    delete = AsyncMock()
    status = AsyncMock(return_value="pending")
    monkeypatch.setattr(K8sService, "create_pod", create)
    monkeypatch.setattr(K8sService, "delete_pod", delete)
    monkeypatch.setattr(K8sService, "get_pod_status", status)
    return create, delete, status


def apply(db, key="request-one", **parameters):
    values = dict(user_id=1, pool_id=1, gpu_count=1, image_id=1, idempotency_key=key)
    values.update(parameters)
    return asyncio.run(SchedulerService.create_allocation(db, **values))


def test_repeated_application_returns_same_instance_and_one_reservation(db, cluster):
    first = apply(db)
    second = apply(db)
    assert first["container_id"] == second["container_id"]
    assert db.query(Allocation).count() == 1
    assert db.query(GPU).filter(GPU.status == GPUStatus.OCCUPIED).count() == 1
    assert (
        db.query(AllocationOperation)
        .filter(AllocationOperation.kind == OperationKind.CREATE)
        .count()
        == 1
    )
    cluster[0].assert_awaited_once()


def test_same_key_with_different_parameters_is_rejected(db, cluster):
    apply(db)
    with pytest.raises(ResourceConflictError):
        apply(db, gpu_count=2)
    assert db.query(Allocation).count() == 1


def test_same_key_is_scoped_to_authenticated_user(db, cluster):
    first = apply(db)
    second = apply(db, user_id=2)
    assert first["container_id"] != second["container_id"]
    assert db.query(Allocation).count() == 2


def test_inflight_retry_from_another_session_does_not_create_again(db, cluster, monkeypatch):
    retries = []

    async def create(**kwargs):
        with sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)() as other:
            retries.append(
                await SchedulerService.create_allocation(
                    other, 1, 1, 1, 1, idempotency_key="request-one"
                )
            )
        return {"status": "pending"}

    method = AsyncMock(side_effect=create)
    monkeypatch.setattr(K8sService, "create_pod", method)
    first = apply(db)
    assert retries[0]["container_id"] == first["container_id"]
    method.assert_awaited_once()
    assert db.query(Allocation).count() == 1


def test_failed_settlement_retry_preserves_original_cutoff(db, cluster, monkeypatch):
    created = apply(db)
    allocation = db.query(Allocation).one()
    allocation.instance.started_at = datetime(2026, 10, 9, 10)
    allocation.start_time = allocation.instance.started_at
    db.get(User, 1).balance = Decimal("100")
    db.commit()
    deleted = [False]

    async def delete(*args, **kwargs):
        deleted[0] = True

    async def status(*args, **kwargs):
        return None if deleted[0] else PodStatus("running", started_at=datetime(2026, 10, 9, 10))

    monkeypatch.setattr(K8sService, "delete_pod", delete)
    monkeypatch.setattr(K8sService, "get_pod_status", status)

    class Clock:
        now = datetime(2026, 10, 9, 11)

        @classmethod
        def utcnow(cls):
            return cls.now

    monkeypatch.setattr(operation_service, "datetime", Clock)
    monkeypatch.setattr(reconciliation_service, "datetime", Clock)
    commit = db.commit
    failure = [True]

    def commit_once_fails_after_delete():
        if allocation.status == AllocationStatus.RELEASED and failure[0]:
            failure[0] = False
            raise RuntimeError("database failed after Pod deletion")
        commit()

    monkeypatch.setattr(db, "commit", commit_once_fails_after_delete)
    with pytest.raises(RuntimeError):
        asyncio.run(SchedulerService.release_allocation(db, 1, created["container_id"]))
    assert deleted[0]
    assert db.query(BillingRecord).count() == 0
    assert allocation.billing_end_time == datetime(2026, 10, 9, 11)
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED
    Clock.now = datetime(2026, 10, 9, 12)
    asyncio.run(ReconciliationService.run_once(db))
    record = db.query(BillingRecord).one()
    assert record.amount == Decimal("5.0000")
    assert record.end_time == datetime(2026, 10, 9, 11)
    assert db.get(User, 1).balance == Decimal("95.0000")
    assert allocation.status == AllocationStatus.RELEASED
    assert db.get(GPU, 1).status == GPUStatus.FREE
    asyncio.run(SchedulerService.release_allocation(db, 1, created["container_id"]))
    assert db.query(BillingRecord).count() == 1


def test_failure_before_release_intent_is_committed_does_not_delete_pod(db, cluster, monkeypatch):
    created = apply(db)
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        asyncio.run(SchedulerService.release_allocation(db, 1, created["container_id"]))
    db.rollback()
    cluster[1].assert_not_called()
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_create_result_commit_failure_is_recovered_without_second_reservation(
    db, cluster, monkeypatch
):
    commit = db.commit
    fail = [True]

    def commit_fails_after_remote_create():
        operation = db.query(AllocationOperation).first()
        if operation and operation.status == OperationStatus.SUCCEEDED and fail[0]:
            fail[0] = False
            raise RuntimeError("result could not be committed")
        commit()

    monkeypatch.setattr(db, "commit", commit_fails_after_remote_create)
    with pytest.raises(RuntimeError):
        apply(db)
    allocation = db.query(Allocation).one()
    operation = db.query(AllocationOperation).one()
    assert allocation.status == AllocationStatus.PENDING
    operation.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    cluster[0].return_value = {"status": "running"}
    cluster[2].return_value = "running"
    asyncio.run(ReconciliationService.run_once(db))
    assert db.query(Allocation).count() == 1
    assert allocation.status == AllocationStatus.ACTIVE
    assert operation.status == OperationStatus.SUCCEEDED
    assert db.query(GPU).filter(GPU.status == GPUStatus.OCCUPIED).count() == 1
    cluster[1].assert_not_called()


def test_querying_instance_list_is_cached_and_does_not_call_cluster(db, cluster):
    apply(db)
    rows = asyncio.run(InstanceService.get_user_instances(db, 1))
    assert rows[0].status == "pending"
    cluster[2].assert_not_called()


def test_background_observation_updates_state_without_user_query(db, cluster):
    apply(db)
    cluster[2].return_value = "running"
    asyncio.run(ReconciliationService.run_once(db))
    assert db.query(Allocation).one().status == AllocationStatus.ACTIVE


def test_unreachable_cluster_never_reclaims_live_gpu(db, cluster):
    apply(db)
    cluster[2].side_effect = ClusterOperationError("cluster unreachable")
    summary = asyncio.run(ReconciliationService.run_once(db))
    assert summary["errors"] == 1
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED
    cluster[1].assert_not_called()


def test_missing_pod_is_cleaned_and_resource_reclaimed(db, cluster):
    apply(db)
    cluster[2].return_value = None
    asyncio.run(ReconciliationService.run_once(db))
    assert db.query(Allocation).one().status == AllocationStatus.RELEASING
    asyncio.run(ReconciliationService.run_once(db))
    assert db.query(Allocation).one().status == AllocationStatus.RELEASED
    assert db.get(GPU, 1).status == GPUStatus.FREE


def test_startup_timeout_queues_cleanup_without_billing(db, cluster):
    apply(db)
    allocation = db.query(Allocation).one()
    allocation.created_at = datetime.utcnow() - timedelta(hours=1)
    db.commit()
    asyncio.run(ReconciliationService.run_once(db))
    asyncio.run(ReconciliationService.run_once(db))
    assert allocation.status == AllocationStatus.FAILED
    assert db.get(GPU, 1).status == GPUStatus.FREE
    assert db.query(BillingRecord).count() == 0


def test_live_operation_lease_prevents_a_second_executor(db, cluster):
    apply(db)
    allocation = db.query(Allocation).one()
    OperationService.queue_release(db, allocation)
    db.commit()
    owner = OperationService._claim(db, allocation.id, OperationKind.RELEASE)
    assert owner is not None
    assert OperationService._claim(db, allocation.id, OperationKind.RELEASE) is None
    operation = OperationService.get(db, allocation.id, OperationKind.RELEASE)
    assert operation.lease_owner == owner
    assert operation.attempts == 1


@pytest.mark.parametrize("observed_before", [False, True])
def test_migrated_admission_failure_only_bills_previously_observed_workload(
    db, cluster, observed_before
):
    apply(db)
    allocation = db.query(Allocation).one()
    started = datetime.utcnow() - timedelta(hours=1)
    allocation.status = AllocationStatus.ACTIVE
    allocation.ready_at = started
    allocation.start_time = started
    allocation.instance.started_at = started
    allocation.last_observed_at = started if observed_before else None
    db.commit()
    cluster[2].return_value = PodStatus(
        "failed", admission_rejected=True, message="GPU admission rejected before startup"
    )
    asyncio.run(ReconciliationService.observe(db, allocation.id))
    release = OperationService.get(db, allocation.id, OperationKind.RELEASE)
    assert release.payload["billable"] is observed_before
    asyncio.run(OperationService.execute_release(db, allocation.id))
    assert allocation.status == AllocationStatus.FAILED
    assert db.get(GPU, 1).status == GPUStatus.FREE
    assert db.query(BillingRecord).count() == int(observed_before)


def test_lost_lease_cannot_commit_or_delete_workload(db, cluster, monkeypatch):
    async def create(**kwargs):
        operation = db.query(AllocationOperation).one()
        operation.lease_owner = "another-executor"
        db.commit()
        return {"status": "running"}

    monkeypatch.setattr(K8sService, "create_pod", create)
    with pytest.raises(ResourceConflictError):
        apply(db)
    assert db.query(Allocation).one().status == AllocationStatus.PENDING
    cluster[1].assert_not_called()
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_failed_release_is_retried_by_background_worker(db, cluster):
    result = apply(db)
    cluster[1].side_effect = ClusterOperationError("delete unavailable")
    with pytest.raises(ClusterOperationError):
        asyncio.run(SchedulerService.release_allocation(db, 1, result["container_id"]))
    operation = OperationService.get(db, db.query(Allocation).one().id, OperationKind.RELEASE)
    assert operation.status == OperationStatus.PENDING
    assert operation.retry_at is not None
    cutoff = db.query(Allocation).one().billing_end_time
    operation.retry_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    cluster[1].side_effect = None
    asyncio.run(ReconciliationService.run_once(db))
    assert db.query(Allocation).one().status == AllocationStatus.RELEASED
    assert db.query(Allocation).one().billing_end_time == cutoff
    assert db.get(GPU, 1).status == GPUStatus.FREE


def test_temporarily_unready_running_instance_is_not_treated_as_startup_timeout(db, cluster):
    cluster[0].return_value = {"status": "running"}
    apply(db)
    allocation = db.query(Allocation).one()
    allocation.created_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    cluster[2].return_value = "pending"
    asyncio.run(ReconciliationService.run_once(db))
    asyncio.run(ReconciliationService.run_once(db))
    cluster[1].assert_not_called()
    assert allocation.ready_at is not None
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED


def test_legacy_pending_request_is_recovered_with_instance_and_operation(db, cluster):
    apply(db)
    allocation = db.query(Allocation).one()
    container_id = allocation.container_id
    db.delete(db.query(AllocationOperation).one())
    db.delete(db.query(Instance).one())
    allocation.status = AllocationStatus.PENDING
    db.commit()
    db.expire(allocation, ["operations", "instance"])
    asyncio.run(ReconciliationService.run_once(db))
    assert allocation.container_id == container_id
    assert allocation.instance is not None
    assert db.query(AllocationOperation).one().status == OperationStatus.SUCCEEDED
    assert db.query(Allocation).count() == 1
    assert db.query(GPU).filter(GPU.status == GPUStatus.OCCUPIED).count() == 1


def test_timeout_scan_cannot_clean_creation_completed_during_remote_read(db, cluster, monkeypatch):
    apply(db)
    allocation = db.query(Allocation).one()
    operation = db.query(AllocationOperation).one()
    allocation.status = AllocationStatus.PENDING
    operation.status = OperationStatus.RUNNING
    operation.created_at = datetime.utcnow() - timedelta(hours=1)
    operation.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    first = [True]

    async def completes_during_read(*args, **kwargs):
        if first[0]:
            first[0] = False
            with sessionmaker(bind=db.get_bind(), expire_on_commit=False)() as other:
                current = other.get(Allocation, allocation.id)
                InstanceService.apply_snapshot(current, "running")
                OperationService._complete(other.get(AllocationOperation, operation.id))
                other.commit()
            return "pending"
        return "running"

    monkeypatch.setattr(K8sService, "get_pod_status", completes_during_read)
    asyncio.run(ReconciliationService.run_once(db))
    assert allocation.status == AllocationStatus.ACTIVE
    assert db.query(AllocationOperation).count() == 1
    assert db.get(GPU, 1).status == GPUStatus.OCCUPIED
    cluster[1].assert_not_called()


def test_explicit_refresh_of_finished_workload_leaves_durable_cleanup(db, cluster):
    cluster[0].return_value = {"status": "running"}
    apply(db)
    cluster[2].return_value = "stopped"
    rows = asyncio.run(InstanceService.get_user_instances(db, 1, refresh=True))
    assert rows[0].status == "stopped"
    assert OperationService.get(db, db.query(Allocation).one().id, OperationKind.RELEASE)
    asyncio.run(ReconciliationService.run_once(db))
    assert db.get(GPU, 1).status == GPUStatus.FREE
    assert db.query(Allocation).one().status == AllocationStatus.STOPPED


def test_access_url_and_namespace_keep_original_creation_configuration(db, cluster, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "INGRESS_HOST", "original.local")
    monkeypatch.setattr(settings, "K8S_NAMESPACE", "original")
    monkeypatch.setattr(settings, "CONTROL_NODE_ID", None)
    cluster[0].return_value = {"status": "running"}
    first = apply(db)
    monkeypatch.setattr(settings, "INGRESS_ENABLED", False)
    monkeypatch.setattr(settings, "INGRESS_HOST", "changed.local")
    monkeypatch.setattr(settings, "K8S_NAMESPACE", "changed")
    assert apply(db)["jupyter_url"] == first["jupyter_url"]
    assert first["jupyter_url"].startswith("http://original.local/")
    asyncio.run(InstanceService.get_user_instances(db, 1, refresh=True))
    assert cluster[2].call_args.kwargs["namespace"] == "original"
    asyncio.run(SchedulerService.release_allocation(db, 1, first["container_id"]))
    assert cluster[1].call_args.kwargs["namespace"] == "original"


def test_configuration_rejects_a_lease_shorter_than_cluster_call_deadlines():
    from pydantic import ValidationError
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="OPERATION_LEASE_SECONDS"):
        Settings(_env_file=None, OPERATION_LEASE_SECONDS=60, K8S_REQUEST_TIMEOUT_SECONDS=10)


def test_environment_template_loads_with_empty_optional_values():
    from pathlib import Path
    from dotenv import dotenv_values
    from app.core.config import Settings

    path = Path(__file__).resolve().parents[1] / ".env.example"
    template = dotenv_values(path)
    assert template["DATABASE_URL"].startswith("mysql+pymysql://")
    assert template["CORS_ORIGINS"].startswith("http://")
    config = Settings(_env_file=path)
    assert config.CONTROL_NODE_ID is None
    assert config.K8S_CONFIG_PATH is None
    assert config.SMTP_PASSWORD is None
