from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.core.dependencies import get_current_user, get_current_admin_user
from app.core.response import success_response
from app.core.exceptions import ResourceNotFoundError
from app.models import User, Node, Allocation, AllocationStatus
from app.core.audit import audit
from app.schemas.telemetry import TelemetryInput
from app.services.telemetry_service import TelemetryService
from app.services.quota_service import QuotaService
from app.infrastructure.kubernetes.runtime_metrics import pod_usage
from app.services.access_service import AccessService

router = APIRouter(tags=["监控与配额"])


@router.get("/admin/maintenance")
def maintenance(user: User = Depends(get_current_admin_user)):
    from app.services.maintenance_service import MaintenanceService

    return success_response(data=MaintenanceService.status())


@router.post("/internal/telemetry")
def ingest(
    body: TelemetryInput,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    accepted = TelemetryService.ingest(db, body, token)
    db.commit()
    return success_response(data={"accepted": accepted})


@router.post("/admin/nodes/{node_id}/monitor-token")
def monitor_token(
    node_id: int,
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    value = TelemetryService.issue_token(db, node_id)
    audit(db, user, "更新采集凭据", "node", node_id)
    db.commit()
    return success_response(data={"token": value})


@router.get("/cluster/node/{node_id}/history")
def history(
    node_id: int,
    minutes: int = Query(default=60, ge=5, le=1440),
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return success_response(data=TelemetryService.history(db, node_id, minutes))


@router.get("/resource/usage")
def usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(data=QuotaService.summary(db, user.id))


@router.get("/resource/{container_id}/metrics")
def instance_metrics(
    container_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allocation = db.query(Allocation).filter_by(container_id=container_id, user_id=user.id).first()
    if not allocation:
        raise ResourceNotFoundError("实例")
    if allocation.status != AllocationStatus.ACTIVE or not allocation.node_id:
        return success_response(
            data={"telemetry_state": "missing", "gpu_list": [], "received_at": None}
        )
    node = db.get(Node, allocation.node_id)
    snapshot = TelemetryService.snapshot(db, node, detail=True)
    owned = [gpu for gpu in snapshot["gpu_list"] if gpu.get("allocation_id") == allocation.id]
    state = snapshot["telemetry_state"]
    if state == "live" and len(owned) != allocation.requested_gpu_count:
        state = "partial"
    try:
        runtime = pod_usage(
            allocation,
            AccessService.allocation_options(allocation).get("namespace", settings.K8S_NAMESPACE),
        )
    except Exception:
        runtime = {
            "state": "missing",
            "cpu_percent": None,
            "memory_percent": None,
            "restart_count": None,
            "last_exit_reason": None,
        }
    return success_response(
        data={
            "telemetry_state": state,
            "received_at": snapshot["received_at"],
            "gpu_list": owned,
            "runtime": runtime,
        }
    )


class QuotaInput(BaseModel):
    inherited: bool = False
    max_gpus: int = Field(default=4, ge=0, le=4096)
    max_instances: int = Field(default=4, ge=0, le=1024)
    low_balance_amount: float = Field(default=10, ge=0, le=1000000, allow_inf_nan=False)
    low_balance_minutes: int = Field(default=30, ge=0, le=10080)
    storage_share_percent: Optional[float] = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    storage_limit_gib: Optional[int] = Field(default=None, ge=1, le=1048576)


@router.get("/admin/quotas/{user_id}")
def quota(
    user_id: int,
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return success_response(data=QuotaService.summary(db, user_id))


@router.post("/admin/quotas/{user_id}")
def set_quota(
    user_id: int,
    body: QuotaInput,
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    value = QuotaService.set_limits(db, user_id, body)
    audit(db, user, "恢复默认配额" if body.inherited else "调整用户配额", "user", user_id)
    db.commit()
    return success_response(data=value)
