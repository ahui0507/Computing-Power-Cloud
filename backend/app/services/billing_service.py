"""按实际运行秒数结算，费用与余额在释放事务中一起提交。"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from sqlalchemy import or_

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError, AuthorizationError, InsufficientBalanceError
from app.core.time import utc_naive
from app.models.billing import BillingMode, BillingRate, BillingRecord
from app.models.gpu_type import GPUType
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.user import User
from app.models.audit import AuditLog

PACKAGES = {"day": (24, Decimal("0.8")), "week": (168, Decimal("0.6"))}


class BillingService:
    @staticmethod
    def package_quote(price, gpu_count, mode):
        hours, discount = PACKAGES[mode]
        unit = (Decimal(str(price)) * hours * discount).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        return unit * gpu_count

    @staticmethod
    def is_package(allocation):
        return allocation.package_paid_at is not None

    @staticmethod
    def purchase_package(db, allocation):
        from app.services.quota_service import QuotaService
        user = QuotaService.lock_user(db, allocation.user_id)
        budget = QuotaService.summary(db, user.id)
        amount = Decimal(str(allocation.package_amount))
        required = amount + Decimal(str(budget["hourly_cost"])) * settings.MINIMUM_BALANCE_MINUTES / 60
        if Decimal(str(budget["available_balance"])) < required:
            raise InsufficientBalanceError(f"包时订单需支付 ¥{amount:.4f}，当前可用余额不足")
        user.balance = Decimal(str(user.balance)) - amount
        allocation.package_paid_at = datetime.utcnow()
        db.add(BillingRecord(allocation_id=allocation.id, instance_id=allocation.instance.id if allocation.instance else None,
            user_id=user.id, gpu_type_id=allocation.gpu_type_id, gpu_count=allocation.requested_gpu_count,
            start_time=allocation.package_paid_at, end_time=allocation.package_paid_at, minutes=0,
            unit_price=amount / allocation.requested_gpu_count, amount=amount,
            billing_mode=BillingMode(allocation.billing_mode.value), settled=True))
        db.add(AuditLog(user_id=user.id, action="购买包时实例", resource_type="allocation", resource_id=str(allocation.id),
            detail={"mode": allocation.billing_mode.value, "amount": str(amount)}, result="success"))

    @staticmethod
    def start_package(db, allocation):
        if not BillingService.is_package(allocation) or not allocation.ready_at or allocation.package_expires_at:
            return
        allocation.package_expires_at = utc_naive(allocation.ready_at) + timedelta(hours=PACKAGES[allocation.billing_mode.value][0])
        record = db.query(BillingRecord).filter_by(allocation_id=allocation.id, settled=True).first()
        if record:
            record.start_time = utc_naive(allocation.ready_at)
            record.end_time = allocation.package_expires_at

    @staticmethod
    def finish_package(db, allocation, ended_at, *, billable=True):
        if not BillingService.is_package(allocation):
            return False
        record = db.query(BillingRecord).filter_by(allocation_id=allocation.id, settled=True).one()
        if allocation.ready_at is None and allocation.package_refunded_at is None:
            user = db.query(User).filter_by(id=allocation.user_id).populate_existing().with_for_update().one()
            user.balance = Decimal(str(user.balance)) + Decimal(str(allocation.package_amount))
            allocation.package_refunded_at = datetime.utcnow()
            record.amount = Decimal(0)
            db.add(AuditLog(user_id=user.id, action="包时创建失败退还余额", resource_type="allocation", resource_id=str(allocation.id),
                detail={"amount": str(allocation.package_amount)}, result="success"))
        end = min(utc_naive(ended_at), utc_naive(allocation.package_expires_at)) if allocation.package_expires_at else utc_naive(ended_at)
        record.end_time = max(utc_naive(record.start_time), end)
        record.minutes = ceil((record.end_time - utc_naive(record.start_time)).total_seconds() / 60)
        return True

    @staticmethod
    def get_hourly_price(db, gpu_type_id: int, at=None) -> Decimal:
        at = utc_naive(at or datetime.utcnow())
        gpu_type = db.get(GPUType, gpu_type_id)
        if gpu_type is None:
            raise ResourceNotFoundError("GPU type")
        rate = (
            db.query(BillingRate)
            .filter(
                BillingRate.gpu_type_id == gpu_type_id,
                BillingRate.billing_mode == BillingMode.HOUR,
                BillingRate.effective_from <= at,
                or_(BillingRate.effective_to.is_(None), BillingRate.effective_to > at),
            )
            .order_by(BillingRate.effective_from.desc())
            .first()
        )
        defaults = {
            "k80": settings.DEFAULT_GPU_PRICE_K80,
            "v100": settings.DEFAULT_GPU_PRICE_V100,
            "a100": settings.DEFAULT_GPU_PRICE_A100,
            "rtx4090": settings.DEFAULT_GPU_PRICE_RTX4090,
        }
        value = rate.price if rate else defaults.get(gpu_type.code.lower(), 10.0)
        price = Decimal(str(value))
        if not price.is_finite() or price < 0:
            raise ValueError("GPU 费率必须为有限的非负数")
        return price.quantize(Decimal("0.0001"))

    @staticmethod
    def get_prices(db) -> dict:
        prices = {
            "k80": settings.DEFAULT_GPU_PRICE_K80,
            "v100": settings.DEFAULT_GPU_PRICE_V100,
            "a100": settings.DEFAULT_GPU_PRICE_A100,
            "rtx4090": settings.DEFAULT_GPU_PRICE_RTX4090,
        }
        for gpu_type in db.query(GPUType).all():
            prices[gpu_type.code.lower()] = float(BillingService.get_hourly_price(db, gpu_type.id))
        return prices

    @staticmethod
    def settle_allocation(db, allocation, ended_at):
        if BillingService.finish_package(db, allocation, ended_at):
            return db.query(BillingRecord).filter_by(allocation_id=allocation.id, settled=True).first()
        # 调用方持有 allocation 行锁。重复释放与事务重试不会重复扣费。
        existing = (
            db.query(BillingRecord)
            .filter(
                BillingRecord.allocation_id == allocation.id,
                BillingRecord.settled.is_(True),
            )
            .first()
        )
        if existing:
            return existing
        instance = allocation.instance
        started_at = (instance.started_at if instance else None) or allocation.start_time
        if started_at is None:
            return None
        start = utc_naive(started_at)
        end = utc_naive(instance.stopped_at if instance and instance.stopped_at else ended_at)
        if allocation.billing_end_time is not None:
            end = min(end, utc_naive(allocation.billing_end_time))
        end = max(start, end)
        seconds = Decimal(str((end - start).total_seconds()))
        price = allocation.hourly_price
        if price is None:
            price = BillingService.get_hourly_price(db, allocation.gpu_type_id, start)
        price = Decimal(str(price)) if settings.BILLING_ENABLED else Decimal("0")
        amount = (price * allocation.requested_gpu_count * seconds / Decimal("3600")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        user = (
            db.query(User)
            .filter(User.id == allocation.user_id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        user.balance = Decimal(str(user.balance)) - amount
        record = BillingRecord(
            allocation_id=allocation.id,
            instance_id=instance.id if instance else None,
            user_id=allocation.user_id,
            gpu_type_id=allocation.gpu_type_id,
            gpu_count=allocation.requested_gpu_count,
            start_time=start,
            end_time=end,
            minutes=ceil(seconds / 60),
            unit_price=price,
            amount=amount,
            billing_mode=BillingMode.HOUR,
            settled=True,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def get_user_records(db, user_id: int):
        return (
            db.query(BillingRecord)
            .filter(BillingRecord.user_id == user_id)
            .order_by(BillingRecord.created_at.desc())
            .all()
        )

    @staticmethod
    def recharge(db, user_id: int, amount) -> float:
        raise AuthorizationError("自助充值已关闭，请使用管理员增加余额接口")
