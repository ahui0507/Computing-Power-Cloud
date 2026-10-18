"""资源 HTTP 接口：校验与响应交给契约，业务编排交给服务。"""

from fastapi import APIRouter, Depends, Header, Response
import asyncio
from typing import Optional
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import ApiResponse, success_response
from app.core.exceptions import OperationNotSupportedError, ResourceConflictError
from app.models.user import User
from app.schemas.resource import (
    ApplyResourceRequest,
    ApplyResourceResponse,
    ContainerResponse,
    ReleaseResourceRequest,
    ReleaseResourceResponse,
    ReleaseScheduleRequest,
    ResourcePoolResponse,
    ResourceSummaryResponse,
)
from app.services.instance_service import InstanceService
from app.services.resource_service import ResourceService
from app.services.scheduler_service import SchedulerService
from app.services.billing_service import BillingService
from app.models import Node, GPUType, GPU
from app.services.telemetry_service import TelemetryService
from app.core.audit import audit
from app.core.gpu_compatibility import architecture_support

router = APIRouter(prefix="/resource", tags=["资源管理"])


@router.get("/summary", response_model=ApiResponse[ResourceSummaryResponse])
async def get_summary(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return success_response(data=ResourceService.get_summary(db))


@router.get("/pools", response_model=ApiResponse[list[ResourcePoolResponse]])
async def get_pools(db: Session = Depends(get_db)):
    def details(pool):
        gpu = db.get(GPUType, pool.gpu_type_id)
        nodes = db.query(Node).filter(Node.id.in_(pool.node_ids or [])).all()
        drivers = sorted(
            {
                node.labels.get("platform.driver_version")
                for node in nodes
                if node.labels and node.labels.get("platform.driver_version")
            }
        )
        cuda = sorted(
            {
                node.labels.get("platform.driver_cuda_max")
                for node in nodes
                if node.labels and node.labels.get("platform.driver_cuda_max")
            }
        )
        gpu_ids = {
            item.id
            for item in db.query(GPU).filter(
                GPU.node_id.in_(pool.node_ids or []),
                GPU.gpu_type_id == pool.gpu_type_id,
            )
        }
        memory = []
        capabilities = set()
        for node in nodes:
            sample = TelemetryService.latest(db, node.id)
            for item in sample.payload.get("gpus", []) if sample else []:
                if item.get("gpu_id") in gpu_ids and item.get("memory_total_mb"):
                    memory.append(item["memory_total_mb"])
                if item.get("gpu_id") in gpu_ids and item.get("compute_capability"):
                    capabilities.add(item["compute_capability"])
        price = BillingService.get_hourly_price(db, pool.gpu_type_id)
        k80 = gpu.code.lower() == "k80"
        capability = (
            next(iter(capabilities)) if len(capabilities) == 1
            else None if capabilities
            else gpu.compute_capability or ("3.7" if k80 else None)
        )
        return dict(
            queue_max_gpus_per_instance=max([db.query(GPU).filter_by(node_id=n.id, gpu_type_id=pool.gpu_type_id).count() for n in nodes] or [0]),
            memory_mb=int(min(memory)) if memory else gpu.memory_mb,
            compute_capability=capability,
            **architecture_support(capability),
            driver_versions=drivers,
            driver_cuda_versions=cuda,
            recommended_environment="CUDA 11.7 / PyTorch 1.13.1（已验证）" if k80 else None,
            hourly_price=float(price),
            daily_price=float(BillingService.package_quote(price, 1, "day")),
            weekly_price=float(BillingService.package_quote(price, 1, "week")),
        )

    return success_response(
        data=[
            ResourcePoolResponse(
                pool_id=pool.id,
                name=pool.name,
                gpu_type=pool.gpu_type,
                total_gpus=ResourceService._calculate_total_gpus(db, pool),
                **ResourceService.pool_capacity(db, pool),
                **details(pool),
            )
            for pool in ResourceService.get_pools(db)
        ]
    )


@router.get("/history", response_model=ApiResponse[list[ContainerResponse]])
def history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = []
    for allocation in ResourceService.get_history(db, current_user):
        row = InstanceService.to_response(db, allocation)
        if current_user.role == "admin":
            row.user_email = allocation.user.email if allocation.user else None
        result.append(row)
    return success_response(data=result)


@router.post("/apply", response_model=ApiResponse[ApplyResourceResponse])
async def apply_resource(
    request: ApplyResourceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
):
    result = await SchedulerService.create_allocation(
        db=db,
        user_id=current_user.id,
        pool_id=request.pool_id,
        gpu_count=request.gpu_count,
        image_id=request.image_id,
        billing_mode=request.billing_mode,
        idempotency_key=idempotency_key,
        duration=request.duration,
    )
    audit(db, current_user, "申请实例", "instance", result["container_id"])
    db.commit()
    return success_response(data=result)


@router.post("/release", response_model=ApiResponse[ReleaseResourceResponse])
async def release_resource(
    request: ReleaseResourceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.release_inspection_service import ReleaseInspectionService
    from app.services.job_service import JobService
    allocation = JobService.allocation(db, current_user.id, request.container_id)
    # End the read transaction before the bounded cluster inspection.
    db.commit()
    await asyncio.to_thread(ReleaseInspectionService.validate, db, allocation, request.confirmation_token, request.confirm_unchecked)
    status = await SchedulerService.release_allocation(db, current_user.id, request.container_id)
    audit(db, current_user, "释放实例", "instance", request.container_id)
    db.commit()
    return success_response(
        data={"container_id": request.container_id, "status": status},
        message="Resource released"
        if status == "released"
        else "Resource release is being recovered",
    )


@router.post("/queue")
def enqueue_resource(body: ApplyResourceRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db), idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")):
    from app.services.resource_queue_service import ResourceQueueService
    return success_response(data=ResourceQueueService.enqueue(db, user.id, body.model_dump(), idempotency_key))


@router.get("/queue")
def resource_queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.resource_queue_service import ResourceQueueService
    return success_response(data=ResourceQueueService.list(db, user.id))


@router.post("/queue/{queue_id}/cancel")
def cancel_queue(queue_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.resource_queue_service import ResourceQueueService
    return success_response(data=ResourceQueueService.cancel(db, user.id, queue_id))


@router.get("/my", response_model=ApiResponse[list[ContainerResponse]])
async def get_my_resources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    refresh: bool = False,
):
    return success_response(
        data=await InstanceService.get_user_instances(db, current_user.id, refresh=refresh)
    )


@router.post("/{container_id}/diagnostics")
async def diagnostics(
    container_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.environment_service import EnvironmentService

    return success_response(data=await EnvironmentService.check(db, user.id, container_id))


@router.post("/{container_id}/release-schedule")
def release_schedule(container_id: str, body: "ReleaseScheduleRequest", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.release_schedule_service import ReleaseScheduleService
    return success_response(data=ReleaseScheduleService.set(db, user.id, container_id, body.release_at))


@router.get("/{container_id}/release-check")
def release_check(container_id: str, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.job_service import JobService
    from app.services.release_inspection_service import ReleaseInspectionService
    allocation = JobService.allocation(db, user.id, container_id)
    response.headers['Cache-Control'] = 'private, no-store'
    db.commit()
    return success_response(data=ReleaseInspectionService.prepare(db, allocation))
