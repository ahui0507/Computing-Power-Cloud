"""
配额模型
"""

from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    DateTime,
    Enum,
    Numeric,
    UniqueConstraint,
    Float,
)
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class OwnerType(str, enum.Enum):
    """所有者类型枚举"""

    USER = "user"
    PROJECT = "project"


class Quota(Base):
    """配额表（用户或项目配额）"""

    __tablename__ = "quotas"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", name="uq_quotas_owner"),)

    id = Column(BigInteger, primary_key=True, index=True, comment="配额ID")
    owner_type = Column(
        Enum(
            OwnerType,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        nullable=False,
        comment="所有者类型",
    )
    owner_id = Column(BigInteger, nullable=False, comment="所有者ID")
    max_gpus = Column(Integer, default=1, nullable=False, comment="最大GPU数")
    max_instances = Column(Integer, default=1, nullable=False, comment="最大实例数")
    storage_share_percent = Column(Float, nullable=True, comment="个人存储占用户存储池的比例")
    storage_limit_bytes = Column(BigInteger, nullable=True, comment="个人持久存储固定字节上限")
    low_balance_amount = Column(Numeric(12, 4), nullable=False, default=10)
    low_balance_minutes = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    def __repr__(self):
        return f"<Quota(id={self.id}, owner_type={self.owner_type}, owner_id={self.owner_id})>"
