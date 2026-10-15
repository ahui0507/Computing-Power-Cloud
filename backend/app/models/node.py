"""
节点和GPU模型
"""
from sqlalchemy import Column, BigInteger, Integer, String, Float, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class NodeStatus(str, enum.Enum):
    """节点状态枚举"""

    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    MAINTENANCE = "maintenance"


class GPUStatus(str, enum.Enum):
    """GPU状态枚举"""

    FREE = "free"
    RESERVED = "reserved"
    OCCUPIED = "occupied"
    MAINTENANCE = "maintenance"


class Node(Base):
    """计算节点表"""

    __tablename__ = "nodes"

    id = Column(BigInteger, primary_key=True, index=True, comment="节点ID")
    hostname = Column(String(128), unique=True, nullable=False, comment="主机名")
    ip = Column(String(64), nullable=False, comment="IP地址")
    cpu_cores = Column(Integer, default=0, comment="CPU核心数")
    memory_gb = Column(Float, default=0.0, comment="内存GB")
    gpus_total = Column(Integer, default=0, comment="总GPU数")
    gpus_free = Column(Integer, default=0, comment="空闲GPU数")
    cpu_usage = Column(Float, default=0.0, comment="CPU使用率")
    mem_usage = Column(Float, default=0.0, comment="内存使用率")
    labels = Column(JSON, nullable=True, comment="标签（JSON格式）")
    status = Column(
        Enum(
            NodeStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=NodeStatus.ONLINE,
        nullable=False,
        comment="状态",
    )
    last_heartbeat = Column(DateTime(timezone=True), nullable=True, comment="最后心跳时间")
    monitor_token_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    gpus = relationship("GPU", back_populates="node", cascade="all, delete-orphan")

    @property
    def name(self) -> str:
        """兼容旧代码，返回hostname"""
        return self.hostname

    def __repr__(self):
        return f"<Node(id={self.id}, hostname={self.hostname}, ip={self.ip})>"


class GPU(Base):
    """GPU表"""

    __tablename__ = "gpus"

    id = Column(BigInteger, primary_key=True, index=True, comment="GPU ID")
    node_id = Column(BigInteger, ForeignKey("nodes.id"), nullable=False, comment="节点ID")
    gpu_index = Column(Integer, nullable=False, comment="GPU索引，如0,1...")
    gpu_type_id = Column(Integer, ForeignKey("gpu_types.id"), nullable=False, comment="GPU类型ID")
    uuid = Column(String(100), unique=True, nullable=True, comment="GPU UUID")
    memory_gb = Column(Float, default=0.0, comment="显存GB")
    status = Column(
        Enum(
            GPUStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=GPUStatus.FREE,
        nullable=False,
        comment="状态",
    )
    occupied_by = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="被哪个用户占用")
    allocation_id = Column(
        BigInteger, ForeignKey("allocations.id"), nullable=True, comment="被哪个分配占用"
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    node = relationship("Node", back_populates="gpus")
    gpu_type = relationship("GPUType", back_populates="gpus")

    @property
    def index(self) -> int:
        """兼容旧代码"""
        return self.gpu_index

    @property
    def model(self) -> str:
        """兼容旧代码，返回GPU类型名称"""
        return self.gpu_type.code if self.gpu_type else "unknown"

    def __repr__(self):
        return f"<GPU(id={self.id}, node_id={self.node_id}, gpu_index={self.gpu_index}, status={self.status})>"
