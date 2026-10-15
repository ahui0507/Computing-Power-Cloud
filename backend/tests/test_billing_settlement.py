import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from app.models import Allocation, BillingRecord, BillingRate, BillingMode, User
from app.services.billing_service import BillingService
from app.services.k8s_service import K8sService
from app.services.scheduler_service import SchedulerService
from app.infrastructure.kubernetes.status import PodStatus


def allocation(db, monkeypatch):
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "pending"}))
    monkeypatch.setattr(K8sService, "delete_pod", AsyncMock())
    asyncio.run(SchedulerService.create_allocation(db, 1, 1, 2, 1))
    return db.query(Allocation).one()


def test_price_api_includes_k80(db):
    assert BillingService.get_prices(db)["k80"] == 5.0


def test_frozen_price_and_exact_runtime_are_settled_once(db, monkeypatch):
    item = allocation(db, monkeypatch)
    start = datetime(2026, 1, 1)
    end = start + timedelta(minutes=15)
    item.instance.started_at = start
    item.instance.stopped_at = end
    db.get(User, 1).balance = Decimal("100")
    db.add(
        BillingRate(
            gpu_type_id=1,
            billing_mode=BillingMode.HOUR,
            price=20,
            effective_from=datetime(2025, 1, 1),
        )
    )
    db.commit()
    record = BillingService.settle_allocation(db, item, end)
    db.commit()
    again = BillingService.settle_allocation(db, item, end + timedelta(hours=1))
    db.commit()
    assert again.id == record.id
    assert record.unit_price == Decimal("5.0000")
    assert record.amount == Decimal("2.5000")
    assert record.minutes == 15
    assert db.get(User, 1).balance == Decimal("97.5000")
    assert db.query(BillingRecord).count() == 1


def test_release_measures_pod_runtime_even_without_ui_polling(db, monkeypatch):
    item = allocation(db, monkeypatch)
    start = datetime.utcnow() - timedelta(minutes=30)
    monkeypatch.setattr(
        K8sService,
        "get_pod_status",
        AsyncMock(
            return_value=PodStatus(
                "stopped",
                started_at=start.replace(tzinfo=timezone.utc),
                finished_at=(start + timedelta(minutes=15)).replace(tzinfo=timezone.utc),
            )
        ),
    )
    asyncio.run(SchedulerService.release_allocation(db, 1, item.container_id))
    asyncio.run(SchedulerService.release_allocation(db, 1, item.container_id))
    record = db.query(BillingRecord).one()
    assert record.amount == Decimal("2.5000")
    assert record.start_time == start


def test_never_started_workload_is_not_charged(db, monkeypatch):
    balance_before = db.get(User, 1).balance
    item = allocation(db, monkeypatch)
    monkeypatch.setattr(K8sService, "get_pod_status", AsyncMock(return_value="failed"))
    asyncio.run(SchedulerService.release_allocation(db, 1, item.container_id))
    assert db.query(BillingRecord).count() == 0
    assert db.get(User, 1).balance == balance_before


def test_settlement_rolls_back_with_its_transaction(db, monkeypatch):
    item = allocation(db, monkeypatch)
    start = datetime(2026, 1, 1)
    item.instance.started_at = start
    db.get(User, 1).balance = Decimal("100")
    db.commit()
    BillingService.settle_allocation(db, item, start + timedelta(hours=1))
    db.rollback()
    assert db.query(BillingRecord).count() == 0
    assert db.get(User, 1).balance == Decimal("100")


def test_settlement_uses_current_balance_after_another_transaction(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    item = allocation(db, monkeypatch)
    start = datetime(2026, 1, 1)
    item.instance.started_at = start
    db.get(User, 1).balance = Decimal("100")
    db.commit()
    with sessionmaker(bind=db.get_bind())() as other:
        other.get(User, 1).balance = Decimal("150")
        other.commit()
    record = BillingService.settle_allocation(db, item, start + timedelta(hours=1))
    db.commit()
    assert record.amount == Decimal("10.0000")
    assert db.get(User, 1).balance == Decimal("140.0000")
