import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models import (
    Allocation,
    AllocationStatus,
    AuditLog,
    BillingRecord,
    GPU,
    Image,
    NodeMetric,
    Notice,
    User,
)
from app.models.operation import AllocationOperation, OperationKind
from app.models.platform_improvements import ResourceQueue, LoginThrottle
from app.services.auth_service import AuthService
from app.services.instance_service import InstanceService
from app.services.k8s_service import K8sService
from app.services.notice_service import NoticeService
from app.services.operational_alert_service import OperationalAlertService
from app.services.release_schedule_service import ReleaseScheduleService
from app.services.resource_queue_service import ResourceQueueService
from app.services.operation_service import OperationService
from app.services.scheduler_service import SchedulerService


@pytest.fixture
def client(db, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        K8sService,
        "create_pod",
        AsyncMock(return_value={"status": "running", "started_at": datetime.utcnow()}),
    )
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="running"))
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def headers(db, user_id=1):
    return {
        "Authorization": "Bearer " + AuthService.create_token(db.get(User, user_id))
    }


def apply(client, db, *, user_id=1, key="one", **changes):
    parameters = dict(pool_id=1, image_id=1, gpu_count=1, billing_mode="on_demand")
    parameters.update(changes)
    return client.post(
        "/resource/apply",
        json=parameters,
        headers={**headers(db, user_id), "Idempotency-Key": key},
    )


def enqueue(client, db, *, user_id=1, key="queue-one", **changes):
    parameters = dict(pool_id=1, image_id=1, gpu_count=1, billing_mode="on_demand")
    parameters.update(changes)
    return client.post(
        "/resource/queue",
        json=parameters,
        headers={**headers(db, user_id), "Idempotency-Key": key},
    )


def test_duration_is_armed_once_after_readiness_and_part_of_idempotency(client, db):
    result = apply(client, db, duration=2)
    assert result.status_code == 200, result.json()
    row = db.query(Allocation).one()
    assert row.scheduled_release_at == row.ready_at + timedelta(hours=2)
    deadline = row.scheduled_release_at
    InstanceService.apply_snapshot(row, "running")
    assert row.scheduled_release_at == deadline
    assert apply(client, db, duration=2).status_code == 200
    assert apply(client, db, duration=3).status_code == 409
    assert db.query(Allocation).count() == 1


def test_schedule_owner_timezone_limits_and_cancel(client, db):
    row_id = apply(client, db).json()["data"]["container_id"]
    url = f"/resource/{row_id}/release-schedule"
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    assert (
        client.post(
            url, json={"release_at": deadline.isoformat()}, headers=headers(db, 2)
        ).status_code
        == 404
    )
    for invalid in (
        datetime.utcnow().isoformat(),
        datetime.now(timezone.utc).isoformat(),
        (deadline + timedelta(days=31)).isoformat(),
    ):
        assert (
            client.post(
                url, json={"release_at": invalid}, headers=headers(db)
            ).status_code
            == 409
        )
    assert (
        client.post(
            url, json={"release_at": deadline.isoformat()}, headers=headers(db)
        ).status_code
        == 200
    )
    row = db.query(Allocation).one()
    NoticeService.refresh(db, now=datetime.utcnow(), force=True)
    assert db.query(Notice).filter(Notice.dedup_key.like("schedule:%")).count() == 1
    assert (
        client.post(url, json={"release_at": None}, headers=headers(db)).status_code
        == 200
    )
    assert row.scheduled_release_at is None and row.release_after_hours is None
    NoticeService.refresh(db, force=True)
    assert all(
        n.expires_at <= datetime.utcnow()
        for n in db.query(Notice).filter(Notice.dedup_key.like("schedule:%"))
    )


def test_pending_duration_can_be_cancelled_before_ready(client, db, monkeypatch):
    monkeypatch.setattr(
        K8sService, "create_pod", AsyncMock(return_value={"status": "pending"})
    )
    result = apply(client, db, duration=1)
    row = db.query(Allocation).one()
    assert row.scheduled_release_at is None
    assert (
        client.post(
            f"/resource/{result.json()['data']['container_id']}/release-schedule",
            json={"release_at": None},
            headers=headers(db),
        ).status_code
        == 200
    )
    InstanceService.apply_snapshot(row, "running")
    assert row.scheduled_release_at is None


def test_scheduled_release_is_recoverable_once_and_bills_original_deadline(client, db):
    apply(client, db)
    row = db.query(Allocation).one()
    now = datetime.utcnow()
    row.ready_at = row.start_time = row.instance.started_at = now - timedelta(hours=2)
    row.scheduled_release_at = now - timedelta(hours=1)
    db.commit()
    ReleaseScheduleService.expire(db, now)
    ReleaseScheduleService.expire(db, now + timedelta(hours=2))
    assert row.status == AllocationStatus.RELEASING
    assert row.billing_end_time == now - timedelta(hours=1)
    assert (
        db.query(AllocationOperation).filter_by(kind=OperationKind.RELEASE).count() == 1
    )
    asyncio.run(OperationService.execute_release(db, row.id))
    assert row.status == AllocationStatus.RELEASED
    assert float(db.query(BillingRecord).one().amount) == 5
    assert all(g.allocation_id is None for g in db.query(GPU))
    assert db.query(AuditLog).filter_by(action="定时自动释放").count() == 1


def test_schedule_defers_image_save_without_moving_billing_cutoff(client, db):
    apply(client, db)
    row = db.query(Allocation).one()
    deadline = datetime.utcnow() - timedelta(seconds=1)
    row.scheduled_release_at = deadline
    image = Image(
        name="saving",
        tag="v1",
        owner_id=1,
        visibility="private",
        snapshot_status="saving",
        source_container_id=row.container_id,
    )
    db.add(image)
    db.commit()
    ReleaseScheduleService.expire(db)
    assert row.status == AllocationStatus.ACTIVE
    image.snapshot_status = "ready"
    db.commit()
    ReleaseScheduleService.expire(db)
    assert row.status == AllocationStatus.RELEASING and row.billing_end_time == deadline


def test_release_check_owner_and_explicit_scope(client, db, monkeypatch):
    from app.services.job_service import JobService

    container_id = apply(client, db).json()["data"]["container_id"]
    monkeypatch.setattr(
        JobService,
        "list",
        lambda db, user_id: [
            dict(
                container_id=container_id, job_id="a", name="training", status="running"
            ),
            dict(container_id="other", job_id="b", name="other", status="running"),
        ],
    )
    url = f"/resource/{container_id}/release-check"
    assert client.get(url, headers=headers(db, 2)).status_code == 404
    result = client.get(url, headers=headers(db)).json()["data"]
    assert result["active_jobs"] == [dict(name="training", job_id="a")]
    assert result["jobs_checked"] and "SSH" in result["message"]
    monkeypatch.setattr(JobService, "list", lambda *a: (_ for _ in ()).throw(OSError()))
    result = client.get(url, headers=headers(db)).json()["data"]
    assert not result["jobs_checked"]


def test_queue_has_no_reservation_or_charge_replays_and_is_owner_limited(client, db):
    one = enqueue(client, db)
    assert one.status_code == 200, one.json()
    assert enqueue(client, db).json()["data"]["id"] == one.json()["data"]["id"]
    assert enqueue(client, db, gpu_count=2).status_code == 409
    assert db.query(Allocation).count() == db.query(BillingRecord).count() == 0
    assert all(g.allocation_id is None for g in db.query(GPU))
    assert client.get("/resource/queue", headers=headers(db, 2)).json()["data"] == []
    queue_id = one.json()["data"]["id"]
    assert (
        client.post(
            f"/resource/queue/{queue_id}/cancel", headers=headers(db, 2)
        ).status_code
        == 404
    )
    assert (
        client.post(f"/resource/queue/{queue_id}/cancel", headers=headers(db)).json()[
            "data"
        ]["status"]
        == "cancelled"
    )
    asyncio.run(ResourceQueueService.run_once(db))
    assert db.query(Allocation).count() == 0


def test_queue_capacity_privacy_limits_and_expiry(client, db):
    assert enqueue(client, db, gpu_count=3).status_code == 409
    assert enqueue(client, db, image_id=2).status_code == 403
    for index in range(3):
        assert enqueue(client, db, key=f"limit-{index}").status_code == 200
    assert enqueue(client, db, key="four").status_code == 409
    asyncio.run(
        ResourceQueueService.run_once(db, datetime.utcnow() + timedelta(days=2))
    )
    assert {r.status for r in db.query(ResourceQueue)} == {"expired"}
    assert db.query(Allocation).count() == 0


def test_queue_waits_then_allocates_once_after_release(client, db):
    first = apply(client, db, gpu_count=2).json()["data"]["container_id"]
    enqueue(client, db, user_id=2)
    asyncio.run(ResourceQueueService.run_once(db))
    assert db.query(ResourceQueue).one().status == "waiting"
    assert db.query(Allocation).count() == 1
    assert (
        client.post(
            "/resource/release", json={"container_id": first}, headers=headers(db)
        ).status_code
        == 200
    )
    asyncio.run(ResourceQueueService.run_once(db))
    asyncio.run(ResourceQueueService.run_once(db))
    queued = db.query(ResourceQueue).one()
    assert queued.status == "started" and queued.container_id
    assert db.query(Allocation).count() == 2
    assert (
        db.query(Notice)
        .filter_by(user_id=2, dedup_key=f"queue:{queued.id}:started")
        .count()
        == 1
    )


def test_expired_dispatch_recovers_existing_allocation_without_duplicate(client, db):
    enqueue(client, db, duration=2)
    queued = db.query(ResourceQueue).one()
    existing = asyncio.run(
        SchedulerService.create_allocation(
            db,
            user_id=1,
            idempotency_key=f"queued-allocation-{queued.id}",
            **queued.parameters,
        )
    )
    queued.status = "dispatching"
    queued.lease_until = queued.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    asyncio.run(ResourceQueueService.run_once(db))
    assert (
        queued.status == "started" and queued.container_id == existing["container_id"]
    )
    assert db.query(Allocation).count() == 1


def test_queue_rechecks_account_state_and_lease_blocks_cancellation(client, db):
    enqueue(client, db)
    row = db.query(ResourceQueue).one()
    row.status, row.lease_until = "dispatching", datetime.utcnow() + timedelta(
        minutes=5
    )
    db.commit()
    assert (
        client.post(f"/resource/queue/{row.id}/cancel", headers=headers(db)).status_code
        == 409
    )
    row.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db.get(User, 1).status = "disabled"
    db.commit()
    asyncio.run(ResourceQueueService.run_once(db))
    assert row.status == "failed" and db.query(Allocation).count() == 0


def test_login_failures_are_shared_rate_limited_and_window_expires(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
    user = db.get(User, 1)
    user.password_hash = get_password_hash("Original123")
    db.commit()
    for _ in range(3):
        assert (
            client.post(
                "/auth/login", json=dict(email=user.email, password="wrong")
            ).status_code
            == 401
        )
    blocked = client.post(
        "/auth/login", json=dict(email=user.email, password="Original123")
    )
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    throttle = db.query(LoginThrottle).one()
    assert user.email not in throttle.key
    throttle.window_start = datetime.utcnow() - timedelta(hours=1)
    db.commit()
    assert (
        client.post(
            "/auth/login", json=dict(email=user.email, password="Original123")
        ).status_code
        == 200
    )
    assert throttle.failures == 0


@pytest.mark.parametrize("action", ["revoke", "password"])
def test_session_revocation_blocks_old_tokens_but_new_login_works(client, db, action):
    user = db.get(User, 1)
    user.password_hash = get_password_hash("Original123")
    db.commit()
    old = headers(db)
    assert client.get("/auth/user_info", headers=old).status_code == 200
    if action == "revoke":
        response = client.post("/account/revoke-sessions", headers=old)
    else:
        response = client.post(
            "/account/password",
            json=dict(old_password="Original123", new_password="Changed123"),
            headers=old,
        )
    assert response.status_code == 200, response.json()
    assert client.get("/auth/user_info", headers=old).status_code == 401
    db.refresh(user)
    assert client.get("/auth/user_info", headers=headers(db)).status_code == 200


def test_operational_alerts_deduplicate_resolve_and_target_admins(db, monkeypatch):
    from app.services.maintenance_service import MaintenanceService

    db.get(User, 2).role_id = 1
    db.commit()
    monkeypatch.setattr(
        MaintenanceService, "status", lambda: {"backup": {"state": "not_configured"}}
    )
    now = datetime.utcnow()
    OperationalAlertService.refresh(db, now)
    OperationalAlertService.refresh(db, now)
    notices = db.query(Notice).all()
    assert len(notices) == 2 and {n.user_id for n in notices} == {2}
    sample = NodeMetric(
        node_id=1,
        collected_at=now,
        received_at=now,
        cpu_usage=1,
        mem_usage=1,
        payload={"gpus": [{"gpu_id": 1, "temperature": 90}]},
    )
    db.add(sample)
    db.commit()
    monkeypatch.setattr(
        MaintenanceService,
        "status",
        lambda: {"backup": {"state": "success", "last_success_at": now.isoformat()}},
    )
    OperationalAlertService.refresh(db, now)
    live = db.query(Notice).filter(Notice.expires_at > now).all()
    assert len(live) == 1 and live[0].title == "GPU 温度预警"
    assert db.query(Allocation).count() == 0


def test_low_utilization_needs_continuous_known_ownership(client, db, monkeypatch):
    from app.services.maintenance_service import MaintenanceService

    apply(client, db)
    row = db.query(Allocation).one()
    now = datetime.utcnow()
    row.ready_at = now - timedelta(hours=1)
    monkeypatch.setattr(
        MaintenanceService,
        "status",
        lambda: {"backup": {"state": "success", "last_success_at": now.isoformat()}},
    )
    for index in range(61):
        time = now - timedelta(seconds=30 * index)
        db.add(
            NodeMetric(
                node_id=1,
                collected_at=time,
                received_at=time,
                cpu_usage=1,
                mem_usage=1,
                payload={
                    "gpus": [
                        {
                            "gpu_id": row.gpu_ids[0],
                            "ownership_known": True,
                            "allocation_id": row.id,
                            "utilization": 0,
                        }
                    ]
                },
            )
        )
    db.commit()
    OperationalAlertService.refresh(db, now)
    assert db.query(Notice).filter_by(title="实例 GPU 持续低利用率", user_id=1).count() == 1
    assert row.status == AllocationStatus.ACTIVE
    for sample in db.query(NodeMetric):
        sample.payload = {"gpus": []}
    db.commit()
    OperationalAlertService.refresh(db, now)
    assert (
        db.query(Notice)
        .filter(Notice.title == "实例 GPU 持续低利用率", Notice.expires_at > now)
        .count()
        == 0
    )
