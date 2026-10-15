"""
支付模型
"""
from sqlalchemy import Column, BigInteger, Numeric, DateTime, ForeignKey, String, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class PaymentMethod(str, enum.Enum):
    """支付方式枚举"""

    BALANCE = "balance"
    ALIPAY = "alipay"
    WECHAT = "wechat"
    BANK = "bank"
    OTHER = "other"


class PaymentStatus(str, enum.Enum):
    """支付状态枚举"""

    INITIATED = "initiated"
    SUCCESS = "success"
    FAILED = "failed"


class Payment(Base):
    """支付表（充值/支付流水）"""

    __tablename__ = "payments"

    id = Column(BigInteger, primary_key=True, index=True, comment="支付ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    invoice_id = Column(BigInteger, ForeignKey("invoices.id"), nullable=True, comment="发票ID")
    amount = Column(Numeric(14, 4), nullable=False, comment="金额")
    method = Column(
        Enum(
            PaymentMethod,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=PaymentMethod.BALANCE,
        nullable=False,
        comment="支付方式",
    )
    status = Column(
        Enum(
            PaymentStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=PaymentStatus.INITIATED,
        nullable=False,
        comment="状态",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    paid_at = Column(DateTime(timezone=True), nullable=True, comment="支付时间")

    # 关系
    user = relationship("User", backref="payments")
    invoice = relationship("Invoice", back_populates="payments")

    def __repr__(self):
        return f"<Payment(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.status})>"
