"""
资源分配模型
"""
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    DateTime,
    ForeignKey,
    JSON,
    Enum,
    Integer,
    Numeric,
    Boolean,
    false,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base
from app.models.enums import enum_values


class AllocationStatus(str, enum.Enum):
    """分配状态枚举"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    STOPPED = "stopped"
    RELEASING = "releasing"
    RELEASED = "released"
    FAILED = "failed"


class BillingMode(str, enum.Enum):
    """计费模式枚举"""

    ON_DEMAND = "on_demand"
    PREPAID = "prepaid"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Allocation(Base):
    """资源分配表"""

    __tablename__ = "allocations"

    id = Column(BigInteger, primary_key=True, index=True, comment="分配ID")
    request_id = Column(String(64), unique=True, nullable=False, comment="请求ID，前端或调度流水号")
    request_fingerprint = Column(String(64), nullable=True, comment="幂等请求参数摘要")
    release_requested_at = Column(DateTime(timezone=True), nullable=True, comment="释放请求接收时间")
    billing_end_time = Column(DateTime(timezone=True), nullable=True, comment="持久化计费截止时间")
    last_observed_at = Column(DateTime(timezone=True), nullable=True, comment="最后成功观测时间")
    last_reconciled_at = Column(DateTime(timezone=True), nullable=True, comment="最后后台核对时间")
    ready_at = Column(DateTime(timezone=True), nullable=True, comment="首次交互服务就绪时间")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    project_id = Column(BigInteger, ForeignKey("projects.id"), nullable=True, comment="项目ID")
    pool_id = Column(Integer, ForeignKey("resource_pools.id"), nullable=True, comment="资源池ID")
    requested_gpu_count = Column(Integer, nullable=False, comment="请求的GPU数量")
    cpu_cores = Column(Integer, nullable=True, comment="申请时冻结的CPU逻辑核心配额")
    cpu_millicores = Column(Integer, nullable=True, comment="申请时冻结的CPU配额毫核")
    node_gpu_count = Column(Integer, nullable=True, comment="比例分配时冻结的节点GPU总数")
    ram_mb = Column(BigInteger, nullable=True, comment="申请时冻结的内存配额MiB")
    compute_reserved = Column(Boolean, nullable=False, default=False, server_default=false(), comment="CPU和内存仍被预留")
    gpu_type_id = Column(Integer, ForeignKey("gpu_types.id"), nullable=True, comment="用户优先选择的GPU类型")
    status = Column(
        Enum(
            AllocationStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=AllocationStatus.PENDING,
        nullable=False,
        comment="状态",
    )
    billing_mode = Column(
        Enum(
            BillingMode,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=False,
            length=20,
        ),
        default=BillingMode.ON_DEMAND,
        nullable=False,
        comment="计费模式",
    )
    image_id = Column(BigInteger, ForeignKey("images.id"), nullable=True, comment="镜像ID")
    image_name = Column(String(200), nullable=True, comment="镜像名称（冗余）")
    hourly_price = Column(Numeric(12, 4), nullable=True, comment="申请时确定的单卡小时价格")
    package_amount = Column(Numeric(14, 4), nullable=True, comment="包日/包周购买时冻结的总价")
    package_paid_at = Column(DateTime(timezone=True), nullable=True)
    package_expires_at = Column(DateTime(timezone=True), nullable=True)
    package_refunded_at = Column(DateTime(timezone=True), nullable=True)
    node_id = Column(BigInteger, ForeignKey("nodes.id"), nullable=True, comment="分配的节点ID")
    gpu_ids = Column(JSON, nullable=True, comment="分配的GPU ID列表")
    container_id = Column(String(100), unique=True, nullable=True, comment="容器ID")
    pod_name = Column(String(200), nullable=True, comment="K8s Pod名称")
    ssh_port = Column(Integer, nullable=True, comment="SSH端口")
    vnc_port = Column(Integer, nullable=True, comment="VNC端口")
    jupyter_port = Column(Integer, nullable=True, comment="Jupyter端口")
    start_time = Column(DateTime(timezone=True), nullable=True, comment="开始时间")
    end_time = Column(DateTime(timezone=True), nullable=True, comment="结束时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 关系
    user = relationship("User", backref="allocations")
    project = relationship("Project", backref="allocations")
    node = relationship("Node", backref="allocations")
    pool = relationship("ResourcePool", backref="allocations")
    image = relationship("Image", backref="allocations")
    gpu_type = relationship("GPUType", backref="allocations")
    instance = relationship(
        "Instance", back_populates="allocation", uselist=False, cascade="all, delete-orphan"
    )
    operations = relationship(
        "AllocationOperation", back_populates="allocation", cascade="all, delete-orphan"
    )

    @property
    def gpu_count(self) -> int:
        """兼容旧代码，返回请求的GPU数量"""
        return self.requested_gpu_count

    @property
    def cpu_quota_millicores(self):
        return self.cpu_millicores if self.cpu_millicores is not None else (self.cpu_cores * 1000 if self.cpu_cores is not None else None)

    @property
    def cpu_quota_cores(self):
        value = self.cpu_quota_millicores
        return value / 1000 if value is not None else None

    def __repr__(self):
        return (
            f"<Allocation(id={self.id}, user_id={self.user_id}, "
            f"request_id={self.request_id}, status={self.status})>"
        )
