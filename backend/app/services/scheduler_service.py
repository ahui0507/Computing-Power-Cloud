"""资源预留和操作意图落库；执行器可以在请求中或后台恢复执行。"""

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    ComputingPlatformException,
    OperationNotSupportedError,
    ResourceNotFoundError,
    ResourceConflictError,
)
from app.models import (
    Allocation,
    AllocationStatus,
    BillingMode,
    Image,
    ImageVisibility,
    Instance,
    InstanceStatus,
)
from app.models.operation import AllocationOperation, OperationKind, OperationStatus
from app.services.access_service import AccessService
from app.services.billing_service import BillingService, PACKAGES
from app.services.instance_service import InstanceService
from app.services.operation_service import OperationService
from app.services.resource_service import ResourceService
from app.services.storage_service import StorageService
from app.services.quota_service import QuotaService
from app.services.compute_budget_service import ComputeBudgetService


class SchedulerService:
    @staticmethod
    def request_identity(user_id, key, parameters):
        fingerprint = hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        request_id = (
            hashlib.sha256(f"{user_id}:{key}".encode()).hexdigest()
            if key
            else f"req-{uuid.uuid4().hex}"
        )
        return request_id, fingerprint

    @staticmethod
    def result(db, allocation, message="Resource request submitted"):
        response = InstanceService.to_response(db, allocation)
        return {
            "container_id": response.container_id,
            "node_id": response.node_id,
            "status": response.status.value,
            "ssh_port": response.ssh_port,
            "vnc_port": response.vnc_port,
            "jupyter_port": response.jupyter_port,
            "jupyter_url": response.jupyter_url,
            "message": message,
        }

    @staticmethod
    def replay(db, allocation, fingerprint):
        if allocation.request_fingerprint != fingerprint:
            raise ResourceConflictError("同一申请标识不能用于不同参数，请重置申请")
        operation = OperationService.get(db, allocation.id, OperationKind.CREATE)
        if operation and operation.status == OperationStatus.FAILED:
            raise ComputingPlatformException(
                status_code=operation.error_code or 409,
                detail=operation.error_message or "该申请已失败，请重置申请后重新提交",
            )
        return SchedulerService.result(db, allocation, "Existing resource request returned")

    @staticmethod
    async def create_allocation(
        db,
        user_id: int,
        pool_id: int,
        gpu_count: int,
        image_id: int,
        billing_mode: str = "on_demand",
        idempotency_key=None,
    ):
        if billing_mode not in ("on_demand", *PACKAGES):
            raise OperationNotSupportedError("请明确选择按时、包日或包周计费")
        parameters = dict(
            pool_id=pool_id,
            gpu_count=gpu_count,
            image_id=image_id,
            billing_mode=billing_mode,
        )
        request_id, fingerprint = SchedulerService.request_identity(
            user_id, idempotency_key, parameters
        )
        if idempotency_key:
            existing = (
                db.query(Allocation)
                .filter(Allocation.request_id == request_id, Allocation.user_id == user_id)
                .first()
            )
            if existing:
                return SchedulerService.replay(db, existing, fingerprint)
        try:
            image = db.get(Image, image_id)
            if image is None:
                raise ResourceNotFoundError("Image")
            if image.visibility != ImageVisibility.PUBLIC and image.owner_id != user_id:
                raise AuthorizationError("无权使用该私有镜像")
            if image.snapshot_status != "ready":
                if image.snapshot_status == "retired":
                    raise ResourceConflictError("该镜像已下架，请重新选择可用镜像")
                raise ResourceConflictError("镜像尚未保存完成，暂时不能创建实例")
            pool = ResourceService.get_pool_by_id(db, pool_id)
            price = (
                BillingService.get_hourly_price(db, pool.gpu_type_id)
                if settings.BILLING_ENABLED
                else 0
            )
            QuotaService.lock_user(db, user_id)
            image = db.query(Image).filter_by(id=image_id).populate_existing().first()
            if image is None:
                raise ResourceNotFoundError("Image")
            if image.snapshot_status != "ready":
                if image.snapshot_status == "retired":
                    raise ResourceConflictError("该镜像已下架，请重新选择可用镜像")
                raise ResourceConflictError("镜像尚未就绪或正在删除，暂时不能创建实例")
            # 等待用户行锁期间，同一幂等请求可能已经完成提交。
            if idempotency_key:
                existing = (
                    db.query(Allocation).filter_by(request_id=request_id, user_id=user_id).first()
                )
                if existing:
                    response = SchedulerService.replay(db, existing, fingerprint)
                    db.rollback()
                    return response
            QuotaService.check_application(
                db,
                user_id,
                gpu_count,
                0 if billing_mode in PACKAGES else price * gpu_count,
            )
            from app.services.storage_quota_service import StorageQuotaService

            StorageQuotaService.prepare(db, user_id)
            # Pool counts are updated in the reservation transaction. Lock it
            # before inserting its FK, then take node and GPU locks in that order.
            pool = ResourceService.get_pool_by_id(db, pool_id, lock=True)
            StorageService.user_root(user_id)
            allocation = Allocation(
                request_id=request_id,
                request_fingerprint=fingerprint,
                user_id=user_id,
                pool_id=pool.id,
                requested_gpu_count=gpu_count,
                gpu_type_id=pool.gpu_type_id,
                image_id=image.id,
                image_name=f"{image.name}:{image.tag}",
                status=AllocationStatus.PENDING,
                billing_mode=BillingMode(billing_mode),
                hourly_price=price,
                package_amount=BillingService.package_quote(price, gpu_count, billing_mode)
                if billing_mode in PACKAGES
                else None,
                created_at=datetime.utcnow(),
            )
            # 先争取唯一请求标识，重复请求不会先竞争 GPU 名额。
            db.add(allocation)
            db.flush()
            node, gpus = ResourceService.find_available_gpus(db, pool_id, gpu_count)
            budget = ComputeBudgetService.node_budget(db, node)
            allocation.cpu_millicores, allocation.ram_mb = ComputeBudgetService.quote(
                budget, gpu_count
            )
            allocation.node_gpu_count = budget["node_gpu_count"]
            allocation.node_id = node.id
            allocation.gpu_ids = [gpu.id for gpu in gpus]
            allocation.container_id = f"container-{allocation.id}-{uuid.uuid4().hex[:8]}"
            allocation.pod_name = f"pod-{allocation.id}-{allocation.container_id[:8]}"
            db.add(
                Instance(
                    allocation=allocation,
                    instance_name=InstanceService.new_name(db, allocation),
                    node_id=node.id,
                    gpu_ids=allocation.gpu_ids,
                    image_id=image.id,
                    status=InstanceStatus.CREATING,
                )
            )
            db.add(
                AllocationOperation(
                    allocation=allocation,
                    kind=OperationKind.CREATE,
                    status=OperationStatus.PENDING,
                    payload=OperationService.creation_payload(
                        node,
                        AccessService.get_jupyter_host(db),
                        image.startup_command or settings.JUPYTER_COMMAND,
                        image.supports_ssh,
                        cpu_cores=allocation.cpu_cores,
                        cpu_millicores=allocation.cpu_millicores,
                        ram_mb=allocation.ram_mb,
                    ),
                )
            )
            ResourceService.allocate_gpus(db, gpus, allocation)
            db.flush()
            if billing_mode in PACKAGES:
                BillingService.purchase_package(db, allocation)
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(Allocation)
                .filter(Allocation.request_id == request_id, Allocation.user_id == user_id)
                .first()
                if idempotency_key
                else None
            )
            if existing:
                return SchedulerService.replay(db, existing, fingerprint)
            raise
        except Exception:
            db.rollback()
            raise

        await OperationService.execute_create(db, allocation.id)
        db.refresh(allocation)
        return SchedulerService.result(db, allocation)

    @staticmethod
    async def release_allocation(db, user_id: int, container_id: str):
        allocation = (
            db.query(Allocation)
            .filter(
                Allocation.container_id == container_id,
                Allocation.user_id == user_id,
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if allocation is None:
            raise ResourceNotFoundError("Allocation")
        if allocation.status == AllocationStatus.RELEASED:
            db.rollback()
            return "released"
        if allocation.status == AllocationStatus.PENDING:
            db.rollback()
            raise ResourceConflictError("实例正在创建，请等待创建结果后再释放")
        if (
            db.query(Image.id)
            .filter_by(source_container_id=container_id, snapshot_status="saving")
            .first()
        ):
            raise ResourceConflictError("个人镜像正在保存，请等待保存完成后再释放实例")
        allocation_id = allocation.id
        operation = OperationService.get(db, allocation_id, OperationKind.RELEASE, lock=True)
        if operation and operation.status == OperationStatus.SUCCEEDED:
            # 创建失败的自动清理已完成，用户确认释放只改变终态。
            allocation.status = AllocationStatus.RELEASED
            db.commit()
            return "released"
        if operation is None:
            OperationService.queue_release(db, allocation)
        elif operation.status == OperationStatus.PENDING:
            operation.retry_at = None  # 用户明确重试时可立即执行，截止时间保持不变。
        db.commit()  # 释放截止时间在任何集群删除调用之前落库。
        await OperationService.execute_release(db, allocation_id)
        db.refresh(allocation)
        return "released" if allocation.status == AllocationStatus.RELEASED else "releasing"
