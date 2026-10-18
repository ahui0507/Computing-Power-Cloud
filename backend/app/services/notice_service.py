"""Deduplicated station reminders, isolated from billing and resource mutations."""

from datetime import datetime, timedelta, timezone
import time
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.time import utc_naive, utc_iso
from app.models import Notice, Allocation, AllocationStatus, User


class NoticeService:
    _last_scan = 0

    @staticmethod
    def emit(
        db,
        user_id,
        key,
        title,
        message,
        *,
        link="/compute/instances",
        allocation_id=None,
        expires_at=None,
    ):
        if db.query(Notice.id).filter_by(user_id=user_id, dedup_key=key).first():
            return
        try:
            with db.begin_nested():
                db.add(
                    Notice(
                        user_id=user_id,
                        dedup_key=key,
                        title=title,
                        message=message,
                        link=link,
                        allocation_id=allocation_id,
                        expires_at=expires_at,
                    )
                )
                db.flush()
        except IntegrityError:
            pass  # Another backend already emitted the same reminder.

    @staticmethod
    def storage_warning(db, user_id, usage, now=None):
        now = utc_naive(now or datetime.utcnow())
        if usage.get("warning") not in ("low", "full"):
            if usage.get("enforcement") == "filesystem":
                db.query(Notice).filter(
                    Notice.user_id == user_id,
                    Notice.dedup_key.like("storage:%"),
                    Notice.expires_at > now,
                ).update({"expires_at": now}, synchronize_session=False)
            return
        kind = usage["warning"]
        NoticeService.emit(
            db,
            user_id,
            f"storage:{now.date()}:{kind}",
            "个人存储额度提醒",
            "个人文件与镜像已接近或达到存储额度，请清理不需要的内容，或联系管理员调整份额。",
            link="/storage",
            expires_at=now + timedelta(days=1),
        )

    @staticmethod
    def refresh(db, now=None, *, force=False):
        if not force and time.monotonic() - NoticeService._last_scan < 60:
            return
        NoticeService._last_scan = time.monotonic()
        now = utc_naive(now or datetime.utcnow())
        active = [
            AllocationStatus.PENDING,
            AllocationStatus.APPROVED,
            AllocationStatus.ACTIVE,
        ]
        rows = db.query(Allocation).filter(Allocation.status.in_(active)).all()
        if settings.INSTANCE_SAFETY_ENABLED:
            from app.services.temporary_storage_monitor import refresh_temporary_storage
            refresh_temporary_storage(db, rows, now)
        for row in rows:
            release_at = utc_naive(row.scheduled_release_at) if row.scheduled_release_at else None
            if release_at and 0 < (release_at - now).total_seconds() <= 3600:
                lead = 10 if (release_at - now).total_seconds() <= 600 else 60
                local_release = release_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
                NoticeService.emit(db, row.user_id, f"schedule:{row.id}:{release_at.isoformat()}:{lead}", "定时释放即将到期", f"实例将于 {local_release} 自动释放，所有运行中的程序会终止。请保存checkpoint、个人文件及需要保留的环境。", allocation_id=row.id, expires_at=release_at)
            deadline = utc_naive(row.package_expires_at) if row.package_expires_at else None
            if deadline and 0 < (deadline - now).total_seconds() <= 3600:
                minutes = (deadline - now).total_seconds() / 60
                lead = 10 if minutes <= 10 else 60
                local = (
                    deadline.replace(tzinfo=timezone.utc)
                    .astimezone(ZoneInfo("Asia/Shanghai"))
                    .strftime("%m-%d %H:%M")
                )
                NoticeService.emit(
                    db,
                    row.user_id,
                    f"package:{row.id}:{deadline.isoformat()}:{lead}",
                    "实例套餐即将到期",
                    f"实例将于 {local} 到期释放，请及时保存文件和模型，并完成个人镜像保存。",
                    allocation_id=row.id,
                    expires_at=deadline,
                )
        for user_id in {row.user_id for row in rows}:
            from app.services.quota_service import QuotaService

            budget = QuotaService.summary(db, user_id, now=now)
            user = db.get(User, user_id)
            if budget["available_balance"] <= settings.DEFAULT_LOW_BALANCE_AMOUNT:
                NoticeService.emit(
                    db,
                    user_id,
                    f"balance:{now.date()}",
                    "可用余额提醒",
                    "可用余额已达到预警范围，请联系管理员补充余额，并留意实例保存期限。",
                    link="/billing",
                    expires_at=now + timedelta(days=1),
                )
            if user.grace_expires_at:
                deadline = utc_naive(user.grace_expires_at)
                minutes = (deadline - now).total_seconds() / 60
                if minutes > 0:
                    NoticeService.emit(
                        db,
                        user_id,
                        f"debt:{deadline.isoformat()}:start",
                        "已进入欠费保存期",
                        "可用余额已耗尽，现有按小时实例保留六小时用于保存成果。请及时保存文件、模型及个人镜像，或联系管理员补足余额。",
                        expires_at=deadline,
                    )
                if 0 < minutes <= 60:
                    lead = 10 if minutes <= 10 else 60
                    NoticeService.emit(
                        db,
                        user_id,
                        f"debt:{deadline.isoformat()}:{lead}",
                        "欠费保存期即将结束",
                        "现有按小时实例即将回收，请尽快保存模型、文件和个人镜像，或联系管理员补足余额。",
                        expires_at=deadline,
                    )
            else:
                db.query(Notice).filter(
                    Notice.user_id == user_id,
                    Notice.dedup_key.like("debt:%"),
                    Notice.expires_at > now,
                ).update({"expires_at": now}, synchronize_session=False)
            if settings.STORAGE_QUOTA_ENABLED:
                from app.services.storage_quota_service import StorageQuotaService

                NoticeService.storage_warning(
                    db, user_id, StorageQuotaService.prepare(db, user_id), now
                )
        ended = db.query(Allocation.id).filter(~Allocation.status.in_(active))
        # Rescheduling and cancelling invalidate reminders for the old deadline.
        valid_schedules = [f"schedule:{r.id}:{utc_naive(r.scheduled_release_at).isoformat()}:{lead}" for r in rows if r.scheduled_release_at for lead in (10, 60)]
        obsolete = db.query(Notice).filter(Notice.dedup_key.like("schedule:%"), Notice.expires_at > now)
        if valid_schedules:
            obsolete = obsolete.filter(~Notice.dedup_key.in_(valid_schedules))
        obsolete.update({"expires_at": now}, synchronize_session=False)
        db.query(Notice).filter(Notice.allocation_id.in_(ended), Notice.expires_at > now).update(
            {"expires_at": now}, synchronize_session=False
        )
        db.query(Notice).filter(
            Notice.created_at < now - timedelta(days=settings.NOTICE_RETENTION_DAYS)
        ).delete(synchronize_session=False)
        db.commit()

    @staticmethod
    def list_for_user(db, user_id):
        now = datetime.utcnow()
        query = db.query(Notice).filter_by(user_id=user_id)
        unread = query.filter(
            Notice.read_at.is_(None),
            or_(Notice.expires_at.is_(None), Notice.expires_at > now),
        ).count()
        rows = query.order_by(Notice.created_at.desc(), Notice.id.desc()).limit(50).all()
        return {
            "unread_count": unread,
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "message": row.message,
                    "link": row.link,
                    "severity": row.severity,
                    "created_at": utc_iso(row.created_at),
                    "read": row.read_at is not None,
                    "expired": bool(row.expires_at and utc_naive(row.expires_at) <= now),
                }
                for row in rows
            ],
        }
