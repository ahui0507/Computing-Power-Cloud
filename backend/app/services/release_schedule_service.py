"""Persist release deadlines and reuse the existing idempotent cleanup and settlement."""
from datetime import datetime, timedelta

from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.core.time import utc_naive, utc_iso
from app.models import Allocation, AllocationStatus, AuditLog, Image

LIVE = (AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE)


class ReleaseScheduleService:
    @staticmethod
    def set(db, user_id, container_id, release_at, now=None):
        now = utc_naive(now or datetime.utcnow())
        row = (
            db.query(Allocation)
            .filter_by(user_id=user_id, container_id=container_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if row is None:
            raise ResourceNotFoundError("实例")
        if row.status not in LIVE:
            raise ResourceConflictError("实例已结束或正在释放，无法修改定时释放")
        if release_at is not None:
            if release_at.tzinfo is None or release_at.utcoffset() is None:
                raise ResourceConflictError("释放时间必须包含时区")
            release_at = utc_naive(release_at)
            if not now + timedelta(minutes=1) <= release_at <= now + timedelta(days=30):
                raise ResourceConflictError("请选择1分钟后至30天内的释放时间")
        row.release_after_hours = (
            None  # Cancelling also cancels a deadline not yet armed.
        )
        row.scheduled_release_at = release_at
        db.add(
            AuditLog(
                user_id=user_id,
                action="设置定时释放" if release_at else "取消定时释放",
                resource_type="allocation",
                resource_id=str(row.id),
                result="success",
            )
        )
        db.commit()
        return {
            "container_id": container_id,
            "scheduled_release_at": utc_iso(release_at),
        }

    @staticmethod
    def expire(db, now=None):
        from app.services.operation_service import OperationService

        now = utc_naive(now or datetime.utcnow())
        ids = [
            r[0]
            for r in db.query(Allocation.id)
            .filter(Allocation.scheduled_release_at <= now, Allocation.status.in_(LIVE))
            .order_by(Allocation.scheduled_release_at)
            .limit(50)
        ]
        for allocation_id in ids:
            row = (
                db.query(Allocation)
                .filter_by(id=allocation_id)
                .populate_existing()
                .with_for_update()
                .one()
            )
            # Recheck after taking the lock: another request may cancel or move the deadline.
            if (
                row.status not in LIVE
                or not row.scheduled_release_at
                or utc_naive(row.scheduled_release_at) > now
            ):
                db.rollback()
                continue
            if row.status == AllocationStatus.PENDING:
                db.rollback()  # Do not race an in-flight create; retry on the next cycle.
                continue
            if (
                db.query(Image.id)
                .filter_by(
                    source_container_id=row.container_id, snapshot_status="saving"
                )
                .first()
            ):
                db.rollback()  # Keep the original billing cutoff while a bounded save completes.
                continue
            deadlines = [utc_naive(row.scheduled_release_at)]
            if row.package_expires_at:
                deadlines.append(utc_naive(row.package_expires_at))
            OperationService.queue_release(db, row, cutoff=min(deadlines))
            if row.instance:
                row.instance.status_message = "定时释放已到期，正在回收资源；个人存储文件保留"
            db.add(
                AuditLog(
                    user_id=row.user_id,
                    action="定时自动释放",
                    resource_type="allocation",
                    resource_id=str(row.id),
                    result="success",
                )
            )
            db.commit()
