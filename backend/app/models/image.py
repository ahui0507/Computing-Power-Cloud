"""
镜像模型
"""
from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class ImageVisibility(str, enum.Enum):
    """镜像可见性枚举"""

    PUBLIC = "public"
    PRIVATE = "private"


class Image(Base):
    """镜像表"""

    __tablename__ = "images"

    id = Column(BigInteger, primary_key=True, index=True, comment="镜像ID")
    name = Column(String(255), nullable=False, comment="镜像名称")
    display_name = Column(String(128), nullable=True, comment="界面显示名称，不改变容器镜像地址")
    tag = Column(String(100), default="latest", nullable=False, comment="标签")
    repo = Column(String(500), nullable=True, comment="仓库地址")
    desc = Column("description", Text, nullable=True, comment="描述")
    size = Column(Numeric(12, 2), default=0.0, comment="大小GB")
    visibility = Column(
        Enum(
            ImageVisibility,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=ImageVisibility.PUBLIC,
        nullable=False,
        comment="可见性",
    )
    owner_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="所有者ID，NULL表示公共镜像")
    startup_command = Column(String(1024), nullable=True, comment="Jupyter 启动程序路径，空值使用平台默认值")
    supports_ssh = Column(Boolean, nullable=False, default=False)
    snapshot_id = Column(String(36), nullable=True, unique=True)
    snapshot_status = Column(String(20), nullable=False, default="ready")
    snapshot_error = Column(Text, nullable=True)
    source_node_id = Column(BigInteger, ForeignKey("nodes.id"), nullable=True)
    source_container_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    owner = relationship("User", backref="images")

    def __repr__(self):
        return f"<Image(id={self.id}, name={self.name}:{self.tag}, visibility={self.visibility})>"
