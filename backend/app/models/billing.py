"""
计费模型
"""
from sqlalchemy import (
    Column,
    BigInteger,
    Numeric,
    DateTime,
    ForeignKey,
    String,
    Enum,
    Integer,
    Boolean,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class BillingMode(str, enum.Enum):
    """计费模式枚举"""

    HOUR = "hour"
    ON_DEMAND = "on_demand"  # 已有数据库中的按时账单旧标记，读取时保留。
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class BillingRate(Base):
    """计费费率表（管理员配置的费率）"""

    __tablename__ = "billing_rates"

    id = Column(BigInteger, primary_key=True, index=True, comment="费率ID")
    gpu_type_id = Column(Integer, ForeignKey("gpu_types.id"), nullable=False, comment="GPU类型ID")
    billing_mode = Column(
        Enum(
            BillingMode,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        nullable=False,
        comment="计费模式",
    )
    price = Column(Numeric(12, 4), nullable=False, default=0.0000, comment="价格，单位：货币/（小时|周|月）")
    currency = Column(String(8), default="CNY", nullable=False, comment="货币")
    effective_from = Column(DateTime(timezone=True), server_default=func.now(), comment="生效开始时间")
    effective_to = Column(DateTime(timezone=True), nullable=True, comment="生效结束时间，NULL表示一直有效")
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="创建者ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关系
    gpu_type = relationship("GPUType", back_populates="billing_rates")
    creator = relationship("User", backref="created_billing_rates")

    def __repr__(self):
        return f"<BillingRate(id={self.id}, gpu_type_id={self.gpu_type_id}, billing_mode={self.billing_mode}, price={self.price})>"


class BillingRecord(Base):
    """计费记录表（计费流水，原子级或分钟级记录）"""

    __tablename__ = "billing_records"

    id = Column(BigInteger, primary_key=True, index=True, comment="记录ID")
    instance_id = Column(BigInteger, ForeignKey("instances.id"), nullable=True, comment="实例ID")
    allocation_id = Column(
        BigInteger, ForeignKey("allocations.id"), nullable=True, comment="分配ID（冗余）"
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    gpu_type_id = Column(Integer, ForeignKey("gpu_types.id"), nullable=False, comment="GPU类型ID")
    gpu_count = Column(Integer, nullable=False, comment="GPU数量")
    start_time = Column(DateTime(timezone=True), nullable=False, comment="开始时间")
    end_time = Column(DateTime(timezone=True), nullable=False, comment="结束时间")
    minutes = Column(Integer, nullable=False, comment="使用时长（分钟）")
    unit_price = Column(Numeric(12, 4), nullable=False, comment="单位价格，结算时从billing_rates复制")
    amount = Column(Numeric(14, 4), nullable=False, comment="金额 = unit_price * factor")
    billing_mode = Column(
        Enum(
            BillingMode,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        nullable=False,
        comment="计费模式",
    )
    settled = Column(Boolean, default=False, nullable=False, comment="是否已结算")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关系
    instance = relationship("Instance", back_populates="billing_records")
    allocation = relationship("Allocation", backref="billing_records")
    user = relationship("User", backref="billing_records")
    gpu_type = relationship("GPUType", backref="billing_records")
    invoice_items = relationship("InvoiceItem", back_populates="billing_record")

    @property
    def container_id(self) -> str:
        """内部路由标识独立于用户可读实例名。"""
        allocation = self.allocation or (self.instance.allocation if self.instance else None)
        return allocation.container_id if allocation else (self.instance.instance_name if self.instance else "")

    def __repr__(self):
        return f"<BillingRecord(id={self.id}, user_id={self.user_id}, amount={self.amount})>"


# 兼容旧代码
BillingPrice = BillingRate
