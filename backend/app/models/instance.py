"""
实例模型（运行的容器/VM/作业）
"""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class InstanceStatus(str, enum.Enum):
    """实例状态枚举"""

    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    ERROR = "error"


class Instance(Base):
    """实例表"""

    __tablename__ = "instances"

    id = Column(BigInteger, primary_key=True, index=True, comment="实例ID")
    allocation_id = Column(BigInteger, ForeignKey("allocations.id"), nullable=False, comment="分配ID")
    instance_name = Column(String(128), nullable=False, comment="实例名称")
    node_id = Column(BigInteger, ForeignKey("nodes.id"), nullable=False, comment="所在节点")
    gpu_ids = Column(JSON, nullable=True, comment="GPU ID列表")
    image_id = Column(BigInteger, ForeignKey("images.id"), nullable=True, comment="镜像ID，个人镜像删除后历史实例保留")
    ssh_port = Column(Integer, nullable=True, comment="SSH端口")
    vnc_port = Column(Integer, nullable=True, comment="VNC端口")
    jupyter_port = Column(Integer, nullable=True, comment="Jupyter端口")
    status = Column(
        Enum(
            InstanceStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=InstanceStatus.CREATING,
        nullable=False,
        comment="状态",
    )
    started_at = Column(DateTime(timezone=True), nullable=True, comment="启动时间")
    stopped_at = Column(DateTime(timezone=True), nullable=True, comment="停止时间")
    status_message = Column(String(512), nullable=True, comment="工作负载状态说明")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    allocation = relationship("Allocation", back_populates="instance")
    node = relationship("Node", backref="instances")
    image = relationship("Image", backref="instances")
    billing_records = relationship("BillingRecord", back_populates="instance")

    def __repr__(self):
        return f"<Instance(id={self.id}, instance_name={self.instance_name}, status={self.status})>"
