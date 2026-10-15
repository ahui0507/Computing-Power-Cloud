from sqlalchemy import (
    Column,
    BigInteger,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.core.database import Base


class Notice(Base):
    __tablename__ = "notices"
    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_notices_user_key"),)
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    allocation_id = Column(BigInteger, ForeignKey("allocations.id"), nullable=True)
    dedup_key = Column(String(200), nullable=False)
    title = Column(String(160), nullable=False)
    message = Column(String(1000), nullable=False)
    severity = Column(String(20), nullable=False, default="warning")
    link = Column(String(200), nullable=False, default="/compute/instances")
    read_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
