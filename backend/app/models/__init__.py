"""
数据库模型
"""

from app.models.role import Role
from app.models.user import User, UserStatus
from app.models.user_profile import UserProfile
from app.models.ssh_key import SSHKey
from app.models.project import Project
from app.models.gpu_type import GPUType
from app.models.operation import AllocationOperation, OperationKind, OperationStatus
from app.models.node import Node, GPU, NodeStatus, GPUStatus
from app.models.resource_pool import ResourcePool
from app.models.allocation import Allocation, AllocationStatus, BillingMode
from app.models.instance import Instance, InstanceStatus
from app.models.image import Image, ImageVisibility
from app.models.quota import Quota, OwnerType
from app.models.billing import (
    BillingRate,
    BillingRecord,
    BillingMode as BillingModeEnum,
)
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.balance_credit import BalanceCredit
from app.models.audit import AuditLog
from app.models.setting import Setting
from app.models.telemetry import NodeMetric
from app.models.backup import Backup, BackupType
from app.models.notice import Notice

__all__ = [
    "Notice",
    "BalanceCredit",
    "NodeMetric",
    "AllocationOperation",
    "OperationKind",
    "OperationStatus",
    "Role",
    "User",
    "UserStatus",
    "UserProfile",
    "SSHKey",
    "Project",
    "GPUType",
    "Node",
    "NodeStatus",
    "GPU",
    "GPUStatus",
    "ResourcePool",
    "Allocation",
    "AllocationStatus",
    "Instance",
    "InstanceStatus",
    "Image",
    "ImageVisibility",
    "Quota",
    "OwnerType",
    "BillingRate",
    "BillingRecord",
    "BillingMode",
    "BillingModeEnum",
    "Invoice",
    "InvoiceItem",
    "InvoiceStatus",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "AuditLog",
    "Setting",
    "Backup",
    "BackupType",
]

# 兼容旧代码
BillingPrice = BillingRate
