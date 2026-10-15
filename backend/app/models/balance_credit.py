"""管理员增加余额的凭证，与充值流水、审计日志在同一事务中保存。"""
from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class BalanceCredit(Base):
    __tablename__ = "balance_credits"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    admin_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    payment_id = Column(BigInteger, ForeignKey("payments.id"), nullable=False, unique=True)
    amount = Column(Numeric(12, 4), nullable=False)
    balance_before = Column(Numeric(12, 4), nullable=False)
    balance_after = Column(Numeric(12, 4), nullable=False)
    reason = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
