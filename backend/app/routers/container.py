"""
容器操作路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.schemas.container import ContainerOperationRequest, ContainerResizeRequest
from app.services.container_service import ContainerService
from app.models.user import User

router = APIRouter(prefix="/container", tags=["容器操作"])


@router.post("/start")
async def start_container(
    request: ContainerOperationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """启动容器"""
    await ContainerService.start_container(db, current_user.id, request.container_id)
    return success_response(message="Container started")


@router.post("/stop")
async def stop_container(
    request: ContainerOperationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """停止容器"""
    await ContainerService.stop_container(db, current_user.id, request.container_id)
    return success_response(message="Container stopped")


@router.post("/restart")
async def restart_container(
    request: ContainerOperationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重启容器"""
    await ContainerService.restart_container(db, current_user.id, request.container_id)
    return success_response(message="Container restarted")


@router.post("/resize")
async def resize_container(
    request: ContainerResizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """调整GPU数量"""
    success = await ContainerService.resize_container(
        db, current_user.id, request.container_id, request.new_gpu_count
    )
    return success_response(data={"success": success}, message="Container resized")
