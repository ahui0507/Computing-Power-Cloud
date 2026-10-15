"""欠费后保留六小时交互时间；个人工作目录不随实例释放而删除。"""
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.config import settings
from app.core.time import utc_naive, utc_iso
from app.models import User, Allocation, AllocationStatus, AuditLog, Image, BillingRecord
from app.services.quota_service import QuotaService


class DebtService:
    @staticmethod
    def depleted_at(db, user, now):
        settled = db.query(BillingRecord.id).filter(BillingRecord.allocation_id == Allocation.id,
            BillingRecord.settled.is_(True)).exists()
        rows = db.query(Allocation).filter(Allocation.user_id == user.id, ~settled,
            Allocation.status != AllocationStatus.RELEASED).all()
        events = {}
        for row in rows:
            if row.package_amount is not None:
                continue
            start = (row.instance.started_at if row.instance else None) or row.start_time
            if not start or (row.status in (AllocationStatus.FAILED, AllocationStatus.STOPPED) and not row.ready_at):
                continue
            start = utc_naive(start)
            end = min([now] + [utc_naive(value) for value in
                (row.billing_end_time, row.instance.stopped_at if row.instance else None) if value is not None])
            if start >= end:
                continue
            rate = QuotaService.rate(db, row)
            events[start] = events.get(start, Decimal(0)) + rate
            events[end] = events.get(end, Decimal(0)) - rate
        funds = Decimal(str(user.balance))
        rate = Decimal(0)
        previous = min(events, default=now)
        for at in sorted(events):
            charge = rate * Decimal(str((at - previous).total_seconds())) / 3600
            if rate > 0 and funds <= charge:
                return previous + timedelta(seconds=float(max(Decimal(0), funds) / rate * 3600))
            funds -= charge
            rate += events[at]
            previous = at
        return now

    @staticmethod
    def update_locked_user(db, user, now=None):
        now = utc_naive(now or datetime.utcnow())
        budget = QuotaService.summary(db, user.id, now=now)
        running = (db.query(Allocation).filter(Allocation.user_id == user.id,
                   Allocation.status.in_([AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE])).all())
        if not settings.BILLING_ENABLED or budget["hourly_cost"] <= 0 or budget["available_balance"] > 0 or not running:
            user.debt_started_at = user.grace_expires_at = None
        elif user.debt_started_at is None:
            # 后台重启或一个扫描周期延迟时，从已产生费用反推余额耗尽时刻。
            user.debt_started_at = DebtService.depleted_at(db, user, now)
            user.grace_expires_at = user.debt_started_at + timedelta(hours=settings.DEBT_GRACE_HOURS)
            db.add(AuditLog(user_id=user.id, action="进入欠费保存期", resource_type="user", resource_id=str(user.id),
                detail={"deadline": utc_iso(user.grace_expires_at), "grace_hours": settings.DEBT_GRACE_HOURS}, result="success"))
        return budget

    @staticmethod
    async def run_once(db, now=None):
        from app.services.operation_service import OperationService
        now = utc_naive(now or datetime.utcnow())
        if not settings.BILLING_ENABLED:
            return
        ids = [row[0] for row in db.query(Allocation.user_id).filter(
            Allocation.status.in_([AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE])).distinct().all()]
        for user_id in ids:
            user = QuotaService.lock_user(db, user_id)
            DebtService.update_locked_user(db, user, now)
            db.commit()
            if not user.grace_expires_at or utc_naive(user.grace_expires_at) > now:
                continue
            allocation_ids = [row[0] for row in db.query(Allocation.id).filter(Allocation.user_id == user_id,
                Allocation.package_amount.is_(None),
                Allocation.status.in_([AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE])).order_by(Allocation.id).all()]
            for allocation_id in allocation_ids:
                # 沿用释放的 allocation -> user 锁顺序；管理员补余额后再次检查，避免误释放。
                allocation = db.query(Allocation).filter_by(id=allocation_id).populate_existing().with_for_update().one()
                user = QuotaService.lock_user(db, user_id)
                budget = DebtService.update_locked_user(db, user, now)
                if budget["available_balance"] > 0 or not user.grace_expires_at or utc_naive(user.grace_expires_at) > now:
                    db.commit()
                    break
                saving = db.query(Image.id).filter_by(source_container_id=allocation.container_id, snapshot_status="saving").first()
                if saving:
                    # 已开始的保存由镜像任务超时控制，避免删除正在读取的系统盘。
                    db.commit()
                    continue
                if allocation.status not in (AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE):
                    db.rollback()
                    continue
                deadline = utc_naive(user.grace_expires_at)
                OperationService.queue_release(db, allocation, cutoff=deadline)
                if allocation.instance:
                    allocation.instance.status_message = "欠费保存期已结束，自动释放；个人存储文件继续保留"
                db.add(AuditLog(user_id=user.id, action="欠费到期自动释放", resource_type="allocation",
                    resource_id=str(allocation.id), detail={"deadline": utc_iso(deadline)}, result="success"))
                db.commit()
