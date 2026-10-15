"""
集群管理路由（管理员）
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_admin_user
from app.core.response import success_response
from app.services.cluster_service import ClusterService
from app.models.user import User
from app.services.telemetry_service import TelemetryService

router = APIRouter(prefix="/cluster", tags=["集群管理"])


@router.get("/nodes")
async def get_nodes(
    current_user: User = Depends(get_current_admin_user), db: Session = Depends(get_db)
):
    """获取所有节点"""
    nodes = ClusterService.get_all_nodes(db)
    return success_response(data=[TelemetryService.snapshot(db, node) for node in nodes])


@router.get("/node/{node_id}")
async def get_node_detail(
    node_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """获取节点详情"""
    node = ClusterService.get_node_detail(db, node_id)
    return success_response(data=TelemetryService.snapshot(db, node, detail=True))


@router.get("/metrics")
async def get_metrics(
    current_user: User = Depends(get_current_admin_user), db: Session = Depends(get_db)
):
    """获取集群监控数据"""
    metrics = ClusterService.get_cluster_metrics(db)
    return success_response(data=metrics)
