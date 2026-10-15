"""
备份模型
"""
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class BackupType(str, enum.Enum):
    """备份类型枚举"""

    SNAPSHOT = "snapshot"
    IMAGE = "image"
    DATA = "data"


class Backup(Base):
    """备份表（快照/镜像备份记录）"""

    __tablename__ = "backups"

    id = Column(BigInteger, primary_key=True, index=True, comment="备份ID")
    instance_id = Column(BigInteger, ForeignKey("instances.id"), nullable=True, comment="实例ID")
    backup_path = Column(String(512), nullable=True, comment="备份路径")
    backup_size = Column(BigInteger, nullable=True, comment="备份大小（字节）")
    backup_type = Column(
        Enum(
            BackupType,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=BackupType.SNAPSHOT,
        nullable=False,
        comment="备份类型",
    )
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="创建者ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")

    # 关系
    instance = relationship("Instance", backref="backups")
    creator = relationship("User", backref="created_backups")

    def __repr__(self):
        return f"<Backup(id={self.id}, instance_id={self.instance_id}, backup_type={self.backup_type})>"
