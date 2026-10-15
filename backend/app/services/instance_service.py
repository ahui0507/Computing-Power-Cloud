"""实例状态同步与 API 投影，集中管理申请和运行状态之间的映射。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re

from app.models.allocation import AllocationStatus
from app.models.instance import InstanceStatus
from app.models.node import Node
from app.models import GPUType, Instance, Allocation
from app.core.time import utc_naive, utc_iso
from app.schemas.resource import ContainerResponse, ContainerStatus
from app.services.access_service import AccessService
from app.services.jupyter_service import JupyterService
from app.services.resource_service import ResourceService


class InstanceService:
    @staticmethod
    def name_base(db, allocation):
        gpu = db.get(GPUType, allocation.gpu_type_id) if allocation.gpu_type_id else None
        code = re.sub(r"[^A-Za-z0-9.-]", "", gpu.code if gpu else "GPU") or "GPU"
        created = utc_naive(allocation.created_at or datetime.utcnow()).replace(tzinfo=timezone.utc)
        return code + "-" + created.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%y%m%d%H%M")

    @staticmethod
    def new_name(db, allocation):
        base = InstanceService.name_base(db, allocation)
        name, suffix = base, 2
        while (
            db.query(Instance.id)
            .join(Allocation)
            .filter(Allocation.user_id == allocation.user_id, Instance.instance_name == name)
            .first()
        ):
            name = f"{base}-{suffix}"
            suffix += 1
        return name

    @staticmethod
    def display_name(db, allocation):
        name = allocation.instance.instance_name if allocation.instance else None
        return (
            name
            if name and not name.startswith("container-")
            else InstanceService.name_base(db, allocation) + f"-{allocation.id}"
        )

    @staticmethod
    def update_runtime(allocation, status, *, started_at=None, finished_at=None, message=None):
        instance = allocation.instance
        started_at = started_at or getattr(status, "started_at", None)
        finished_at = finished_at or getattr(status, "finished_at", None)
        if instance:
            instance.status_message = message or getattr(status, "message", None)
            if started_at and instance.started_at is None:
                instance.started_at = utc_naive(started_at)
                allocation.start_time = instance.started_at
            if finished_at and status in ("failed", "stopped"):
                instance.stopped_at = utc_naive(finished_at)
            if status == "running":
                instance.stopped_at = None
                if instance.started_at is None:
                    instance.started_at = datetime.utcnow()
                allocation.start_time = instance.started_at

    @staticmethod
    def apply_snapshot(allocation, status, *, started_at=None, finished_at=None, message=None):
        if allocation.status in (AllocationStatus.RELEASED, AllocationStatus.RELEASING):
            return
        InstanceService.update_runtime(
            allocation, status, started_at=started_at, finished_at=finished_at, message=message
        )
        allocation.last_observed_at = (
            datetime.utcnow() if status is not None else allocation.last_observed_at
        )
        instance = allocation.instance
        if status == "running":
            allocation.status = AllocationStatus.ACTIVE
            allocation.ready_at = allocation.ready_at or datetime.utcnow()
            if instance:
                instance.status = InstanceStatus.RUNNING
                instance.stopped_at = None
                if instance.started_at is None:
                    instance.started_at = datetime.utcnow()
                allocation.start_time = instance.started_at
        elif status == "pending":
            allocation.status = AllocationStatus.APPROVED
            if instance:
                instance.status = InstanceStatus.CREATING
        elif status == "stopped":
            allocation.status = AllocationStatus.STOPPED
            if instance:
                instance.status = InstanceStatus.STOPPED
        else:
            allocation.status = AllocationStatus.FAILED
            if instance:
                instance.status = InstanceStatus.ERROR

    @staticmethod
    def get_status(allocation) -> ContainerStatus:
        if allocation.status == AllocationStatus.RELEASED:
            return ContainerStatus.RELEASED
        if allocation.status == AllocationStatus.RELEASING:
            return ContainerStatus.RELEASING
        if allocation.status in (AllocationStatus.FAILED, AllocationStatus.REJECTED):
            return ContainerStatus.FAILED
        if allocation.status == AllocationStatus.STOPPED:
            return ContainerStatus.STOPPED
        if allocation.status == AllocationStatus.ACTIVE:
            return ContainerStatus.RUNNING
        return ContainerStatus.PENDING

    @staticmethod
    def to_response(db, allocation) -> ContainerResponse:
        from app.core.workspace import persistent_path, LEGACY_LAYOUT

        options = AccessService.allocation_options(allocation)
        node = db.get(Node, allocation.node_id) if allocation.node_id else None
        status = InstanceService.get_status(allocation)
        running = status == ContainerStatus.RUNNING
        return ContainerResponse(
            persistent_path=persistent_path(options),
            storage_layout=options.get("storage_layout", LEGACY_LAYOUT),
            container_id=allocation.container_id or f"alloc-{allocation.id}",
            instance_name=InstanceService.display_name(db, allocation),
            node_id=allocation.node_id or 0,
            node_ip=node.ip if node else None,
            gpus=allocation.requested_gpu_count,
            cpu_cores=allocation.cpu_quota_cores,
            node_gpu_count=allocation.node_gpu_count,
            ram_mb=allocation.ram_mb,
            image=allocation.image_name or "unknown",
            status=status,
            start_time=utc_iso(allocation.start_time),
            created_at=utc_iso(allocation.created_at),
            end_time=utc_iso(allocation.billing_end_time or allocation.end_time),
            hourly_price=float(allocation.hourly_price)
            if allocation.hourly_price is not None
            else None,
            billing_mode=allocation.billing_mode.value,
            package_amount=float(allocation.package_amount)
            if allocation.package_amount is not None
            else None,
            package_expires_at=utc_iso(allocation.package_expires_at),
            package_refunded=allocation.package_refunded_at is not None,
            settled_amount=sum(
                float(record.amount) for record in allocation.billing_records if record.settled
            )
            if any(record.settled for record in allocation.billing_records)
            else None,
            pool_id=allocation.pool_id,
            image_id=allocation.image_id,
            status_message=allocation.instance.status_message if allocation.instance else None,
            ssh_port=allocation.ssh_port if running else None,
            ssh_enabled=bool(AccessService.allocation_options(allocation).get("ssh_enabled")),
            vnc_port=allocation.vnc_port if running else None,
            jupyter_port=allocation.jupyter_port if running else None,
            jupyter_url=JupyterService.authenticated_url(
                AccessService.get_jupyter_url(
                    db,
                    allocation.id,
                    node_ip=node.ip if node else None,
                    port=allocation.jupyter_port,
                    options=AccessService.allocation_options(allocation),
                ),
                allocation.id,
                allocation.user_id,
            )
            if running
            else None,
        )

    @staticmethod
    async def get_user_instances(db, user_id: int, *, refresh=False):
        allocations = ResourceService.get_user_allocations(db, user_id)
        if not refresh:
            return [InstanceService.to_response(db, allocation) for allocation in allocations]
        watched = [
            allocation
            for allocation in allocations
            if allocation.pod_name
            and allocation.status in (AllocationStatus.APPROVED, AllocationStatus.ACTIVE)
        ]
        # 显式刷新与后台使用同一套核对规则，终态也留下可恢复的清理意图。
        from app.services.reconciliation_service import ReconciliationService

        for allocation_id in [allocation.id for allocation in watched]:
            await ReconciliationService.observe(db, allocation_id)
        return [InstanceService.to_response(db, allocation) for allocation in allocations]
