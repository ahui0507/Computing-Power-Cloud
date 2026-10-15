"""
发票模型
"""
from sqlalchemy import Column, BigInteger, Numeric, DateTime, ForeignKey, String, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class InvoiceStatus(str, enum.Enum):
    """发票状态枚举"""

    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class Invoice(Base):
    """发票表（发票/结算单）"""

    __tablename__ = "invoices"

    id = Column(BigInteger, primary_key=True, index=True, comment="发票ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    invoice_no = Column(String(64), unique=True, nullable=False, comment="发票号")
    period_start = Column(DateTime(timezone=True), nullable=False, comment="周期开始")
    period_end = Column(DateTime(timezone=True), nullable=False, comment="周期结束")
    total_amount = Column(Numeric(14, 4), nullable=False, comment="总金额")
    status = Column(
        Enum(
            InvoiceStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=InvoiceStatus.PENDING,
        nullable=False,
        comment="状态",
    )
    issued_at = Column(DateTime(timezone=True), server_default=func.now(), comment="开具时间")
    paid_at = Column(DateTime(timezone=True), nullable=True, comment="支付时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关系
    user = relationship("User", backref="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice")

    def __repr__(self):
        return f"<Invoice(id={self.id}, invoice_no={self.invoice_no}, total_amount={self.total_amount})>"


class InvoiceItem(Base):
    """发票明细表（把billing_records聚合进发票明细）"""

    __tablename__ = "invoice_items"

    id = Column(BigInteger, primary_key=True, index=True, comment="明细ID")
    invoice_id = Column(BigInteger, ForeignKey("invoices.id"), nullable=False, comment="发票ID")
    billing_record_id = Column(
        BigInteger, ForeignKey("billing_records.id"), nullable=False, comment="计费记录ID"
    )
    amount = Column(Numeric(14, 4), nullable=False, comment="金额")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关系
    invoice = relationship("Invoice", back_populates="items")
    billing_record = relationship("BillingRecord", back_populates="invoice_items")

    def __repr__(self):
        return f"<InvoiceItem(id={self.id}, invoice_id={self.invoice_id}, amount={self.amount})>"
