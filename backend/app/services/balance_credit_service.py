from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.core.time import utc_iso
from app.models import User, BalanceCredit, Payment, PaymentMethod, PaymentStatus, AuditLog


class BalanceCreditService:
    @staticmethod
    def serialize(row):
        return {
            "id": row.id, "request_id": row.request_id, "user_id": row.user_id,
            "admin_id": row.admin_id, "amount": float(row.amount),
            "balance_before": float(row.balance_before), "balance_after": float(row.balance_after),
            "reason": row.reason, "created_at": utc_iso(row.created_at),
        }

    @staticmethod
    def add(db, admin, user_id, request):
        # 与实例扣费和其他充值共用用户行锁，锁后重新读取最新余额。
        user = (db.query(User).filter(User.id == user_id, User.deleted_at.is_(None))
                .populate_existing().with_for_update().first())
        if user is None:
            raise ResourceNotFoundError("User")
        request_id = str(request.request_id)
        existing = db.query(BalanceCredit).filter_by(request_id=request_id).first()
        if existing:
            if (existing.user_id != user_id or existing.admin_id != admin.id
                    or existing.amount != request.amount or existing.reason != request.reason):
                raise ResourceConflictError("该请求编号已用于其他余额操作")
            return existing
        if user.role != "user":
            raise ResourceConflictError("仅支持为普通用户增加余额")
        before = Decimal(str(user.balance))
        after = before + request.amount
        if after > Decimal("99999999.9999"):
            raise ResourceConflictError("增加后余额超过账户上限")
        payment = Payment(user_id=user_id, amount=request.amount, method=PaymentMethod.OTHER,
                          status=PaymentStatus.SUCCESS, paid_at=datetime.utcnow())
        db.add(payment)
        db.flush()
        row = BalanceCredit(request_id=request_id, user_id=user_id, admin_id=admin.id,
                            payment_id=payment.id, amount=request.amount, balance_before=before,
                            balance_after=after, reason=request.reason)
        user.balance = after
        from app.services.debt_service import DebtService
        DebtService.update_locked_user(db, user)
        db.add(row)
        db.add(AuditLog(user_id=admin.id, action="增加用户余额", resource_type="user",
                        resource_id=str(user_id), result="success", detail={
                            "request_id": request_id, "amount": str(request.amount),
                            "balance_before": str(before), "balance_after": str(after),
                            "reason": request.reason, "target_email": user.email,
                        }))
        try:
            db.commit()
        except IntegrityError as exc:
            # 不同目标用户同时误用同一个编号时，唯一约束会回滚整笔操作。
            db.rollback()
            raise ResourceConflictError("请求编号发生冲突，请核对操作记录") from exc
        db.refresh(row)
        return row

    @staticmethod
    def history(db, user_id, page, page_size):
        query = db.query(BalanceCredit).filter_by(user_id=user_id)
        return {"total": query.count(), "items": [BalanceCreditService.serialize(row) for row in
                query.order_by(BalanceCredit.id.desc()).offset((page - 1) * page_size).limit(page_size).all()]}
