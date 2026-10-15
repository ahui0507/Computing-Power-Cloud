"""用户行锁串行化申请；配额、预估未结算费用与余额采用同一口径。"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP

from app.core.config import settings
from app.core.exceptions import (
    InsufficientBalanceError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.core.time import utc_naive
from app.core.time import utc_iso
from app.models import (
    Allocation,
    AllocationStatus,
    BillingRecord,
    GPU,
    OwnerType,
    Quota,
    User,
)
from app.services.billing_service import BillingService

MONEY = Decimal("0.0001")
CURRENT = (
    AllocationStatus.PENDING,
    AllocationStatus.APPROVED,
    AllocationStatus.ACTIVE,
    AllocationStatus.RELEASING,
)


class QuotaService:
    @staticmethod
    def limits(db, user_id):
        quota = db.query(Quota).filter_by(owner_type=OwnerType.USER, owner_id=user_id).first()
        user = db.get(User, user_id)
        default_bytes = (user.storage_default_bytes if user else None) or settings.DEFAULT_STORAGE_LIMIT_GIB * 1024**3
        fixed_bytes = quota.storage_limit_bytes if quota and quota.storage_limit_bytes is not None else default_bytes
        return {
            "inherited": quota is None,
            "storage_share_percent": quota.storage_share_percent
            if quota and quota.storage_share_percent is not None
            else settings.DEFAULT_STORAGE_SHARE_PERCENT,
            "storage_mode": settings.STORAGE_QUOTA_MODE,
            "storage_limit_gib": fixed_bytes / 1024**3,
            "storage_inherited": (quota is None or quota.storage_limit_bytes is None)
            if settings.STORAGE_QUOTA_MODE == "fixed"
            else (quota is None or quota.storage_share_percent is None),
            "max_gpus": quota.max_gpus if quota else settings.DEFAULT_MAX_USER_GPUS,
            "max_instances": quota.max_instances if quota else settings.DEFAULT_MAX_USER_INSTANCES,
            "low_balance_amount": settings.DEFAULT_LOW_BALANCE_AMOUNT,
            "low_balance_minutes": 0,
        }

    @staticmethod
    def rate(db, allocation):
        if not settings.BILLING_ENABLED or allocation.package_amount is not None:
            return Decimal("0")
        value = allocation.hourly_price
        if value is None:
            value = BillingService.get_hourly_price(db, allocation.gpu_type_id)
        return Decimal(str(value)) * allocation.requested_gpu_count

    @staticmethod
    def estimate(db, allocation, now=None):
        if allocation.package_amount is not None:
            return Decimal(0)
        instance = allocation.instance
        start = (instance.started_at if instance else None) or allocation.start_time
        if start is None or not settings.BILLING_ENABLED:
            return Decimal("0")
        # 从未就绪且免计费的失败创建不计入费用预警。
        if (
            allocation.status in (AllocationStatus.FAILED, AllocationStatus.STOPPED)
            and allocation.ready_at is None
        ):
            return Decimal("0")
        end = utc_naive(now or datetime.utcnow())
        for cutoff in [
            allocation.billing_end_time,
            instance.stopped_at if instance else None,
        ]:
            if cutoff is not None:
                end = min(end, utc_naive(cutoff))
        seconds = Decimal(str(max(0, (end - utc_naive(start)).total_seconds())))
        return (QuotaService.rate(db, allocation) * seconds / Decimal(3600)).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )

    @staticmethod
    def summary(db, user_id, *, now=None):
        user = db.get(User, user_id)
        if not user:
            raise ResourceNotFoundError("用户")
        limits = QuotaService.limits(db, user_id)
        held = db.query(GPU.id).filter(GPU.allocation_id == Allocation.id).exists()
        current = (
            db.query(Allocation)
            .filter(
                Allocation.user_id == user_id,
                (Allocation.status.in_(CURRENT)) | held | Allocation.compute_reserved.is_(True),
            )
            .all()
        )
        used_gpus = sum(row.requested_gpu_count for row in current)
        hourly = sum(
            (
                QuotaService.rate(db, row)
                for row in current
                if row.status
                in (
                    AllocationStatus.PENDING,
                    AllocationStatus.APPROVED,
                    AllocationStatus.ACTIVE,
                )
            ),
            Decimal(0),
        )
        settled = (
            db.query(BillingRecord.id)
            .filter(
                BillingRecord.allocation_id == Allocation.id,
                BillingRecord.settled.is_(True),
            )
            .exists()
        )
        unbilled = (
            db.query(Allocation)
            .filter(
                Allocation.user_id == user_id,
                ~settled,
                Allocation.status != AllocationStatus.RELEASED,
            )
            .all()
        )
        estimate = sum((QuotaService.estimate(db, row, now) for row in unbilled), Decimal(0))
        balance = Decimal(str(user.balance or 0))
        available = (balance - estimate).quantize(MONEY)
        remaining = max(Decimal(0), available) / hourly * 60 if hourly > 0 else None
        warning = "none"
        if settings.BILLING_ENABLED:
            if available <= 0:
                warning = "insufficient"
            elif available <= Decimal(str(limits["low_balance_amount"])) or (
                remaining is not None and remaining <= limits["low_balance_minutes"]
            ):
                warning = "low"
        return {
            **limits,
            "default_limits": {
                "max_gpus": settings.DEFAULT_MAX_USER_GPUS,
                "storage_share_percent": settings.DEFAULT_STORAGE_SHARE_PERCENT,
                "storage_limit_gib": settings.DEFAULT_STORAGE_LIMIT_GIB,
                "max_instances": settings.DEFAULT_MAX_USER_INSTANCES,
                "low_balance_amount": settings.DEFAULT_LOW_BALANCE_AMOUNT,
                "low_balance_minutes": settings.DEFAULT_LOW_BALANCE_MINUTES,
            },
            "used_gpus": used_gpus,
            "used_instances": len(current),
            "used_cpu_cores": sum(row.cpu_quota_millicores or 0 for row in current) / 1000,
            "used_ram_mb": sum(row.ram_mb or 0 for row in current),
            "remaining_gpus": max(0, limits["max_gpus"] - used_gpus),
            "remaining_instances": max(0, limits["max_instances"] - len(current)),
            "balance": float(balance),
            "unsettled_estimate": float(estimate),
            "available_balance": float(available),
            "hourly_cost": float(hourly),
            "estimated_remaining_minutes": float(remaining) if remaining is not None else None,
            "warning": warning,
            "minimum_balance_minutes": settings.MINIMUM_BALANCE_MINUTES,
            "debt_started_at": utc_iso(user.debt_started_at),
            "grace_expires_at": utc_iso(user.grace_expires_at),
            "grace_hours": settings.DEBT_GRACE_HOURS,
            "billing_enabled": settings.BILLING_ENABLED,
        }

    @staticmethod
    def lock_user(db, user_id):
        user = db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
        if not user:
            raise ResourceNotFoundError("用户")
        return user

    @staticmethod
    def check_application(db, user_id, gpu_count, new_hourly_rate):
        # 不锁分配记录，避免与“分配 -> 用户 -> GPU”的释放锁顺序形成循环。
        QuotaService.lock_user(db, user_id)
        budget = QuotaService.summary(db, user_id)
        if gpu_count > budget["remaining_gpus"]:
            raise ResourceConflictError(
                f"GPU 配额不足：上限 {budget['max_gpus']} 张，已占用 {budget['used_gpus']} 张，本次申请 {gpu_count} 张"
            )
        if budget["remaining_instances"] < 1:
            raise ResourceConflictError(
                f"实例配额不足：最多 {budget['max_instances']} 个，当前 {budget['used_instances']} 个"
            )
        if settings.BILLING_ENABLED:
            hourly = Decimal(str(budget["hourly_cost"])) + Decimal(str(new_hourly_rate))
            required = (hourly * settings.MINIMUM_BALANCE_MINUTES / 60).quantize(
                MONEY, rounding=ROUND_UP
            )
            if hourly > 0 and (
                Decimal(str(budget["available_balance"])) <= 0
                or Decimal(str(budget["available_balance"])) < required
            ):
                raise InsufficientBalanceError(
                    f"可用余额不足：扣除运行中预估费用后剩余 ¥{budget['available_balance']:.4f}，需至少覆盖全部实例未来 {settings.MINIMUM_BALANCE_MINUTES} 分钟费用 ¥{required:.4f}"
                )

    @staticmethod
    def set_limits(db, user_id, body):
        user = db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
        if not user:
            raise ResourceNotFoundError("用户")
        quota = db.query(Quota).filter_by(owner_type=OwnerType.USER, owner_id=user_id).first()
        if body.inherited:
            if quota:
                db.delete(quota)
        else:
            if quota is None:
                quota = Quota(owner_type=OwnerType.USER, owner_id=user_id)
                db.add(quota)
            quota.max_gpus = body.max_gpus
            quota.max_instances = body.max_instances
            quota.low_balance_amount = body.low_balance_amount
            quota.low_balance_minutes = body.low_balance_minutes
            if "storage_share_percent" in getattr(body, "model_fields_set", set()):
                quota.storage_share_percent = body.storage_share_percent
            if "storage_limit_gib" in getattr(body, "model_fields_set", set()):
                quota.storage_limit_bytes = (
                    body.storage_limit_gib * 1024**3 if body.storage_limit_gib is not None else None
                )
        db.flush()
        if settings.STORAGE_QUOTA_ENABLED:
            from app.services.storage_quota_service import StorageQuotaService

            StorageQuotaService.prepare(db, user_id)
        return QuotaService.summary(db, user_id)
