"""可恢复的资源操作日志，保留操作意图、租约和重试状态。"""
import enum

from sqlalchemy import (
    Column,
    BigInteger,
    String,
    DateTime,
    ForeignKey,
    JSON,
    Enum,
    Integer,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import enum_values


class OperationKind(str, enum.Enum):
    CREATE = "create"
    RELEASE = "release"


class OperationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AllocationOperation(Base):
    __tablename__ = "allocation_operations"
    __table_args__ = (
        UniqueConstraint("allocation_id", "kind", name="uq_allocation_operation_kind"),
        Index("ix_allocation_operations_ready", "status", "retry_at", "lease_until"),
    )
    id = Column(BigInteger, primary_key=True)
    allocation_id = Column(
        BigInteger, ForeignKey("allocations.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(
        Enum(OperationKind, values_callable=enum_values, native_enum=False, length=20),
        nullable=False,
    )
    status = Column(
        Enum(OperationStatus, values_callable=enum_values, native_enum=False, length=20),
        nullable=False,
        default=OperationStatus.PENDING,
    )
    payload = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(64), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    retry_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(Integer, nullable=True)
    error_message = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    allocation = relationship("Allocation", back_populates="operations")
