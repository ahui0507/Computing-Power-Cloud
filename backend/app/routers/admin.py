"""
管理员路由
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_admin_user
from app.core.response import success_response, error_response, ApiResponse
from app.core.exceptions import ResourceNotFoundError
from app.schemas.admin import (
    SetRoleRequest,
    CreatePoolRequest,
    AddBalanceRequest,
    CreateUserRequest,
)
from app.schemas.user import UserInfo
from app.services.balance_credit_service import BalanceCreditService
from app.services.admin_service import AdminService
from app.models.user import User
from app.models.gpu_type import GPUType
from app.core.audit import audit
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/admin", tags=["管理员"])


@router.post("/users", response_model=ApiResponse[UserInfo])
def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    user = AdminService.create_user(db, current_user, request.email)
    return success_response(
        data={
            "user_id": user.id,
            "email": user.email,
            "role": user.role,
            "balance": float(user.balance),
        },
        message="账号已创建",
    )


@router.post("/users/{user_id}/balance-credits")
def add_balance(
    user_id: int,
    request: AddBalanceRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    row = BalanceCreditService.add(db, current_user, user_id, request)
    return success_response(data=BalanceCreditService.serialize(row), message="余额已增加")


@router.get("/users/{user_id}/balance-credits")
def balance_credit_history(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    if not db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first():
        raise ResourceNotFoundError("User")
    return success_response(data=BalanceCreditService.history(db, user_id, page, page_size))


@router.get("/users")
async def get_users(
    current_user: User = Depends(get_current_admin_user), db: Session = Depends(get_db)
):
    """获取所有用户"""
    users = AdminService.get_all_users(db)
    return success_response(
        data=[
            {
                "user_id": user.id,
                "email": user.email or "",
                "role": user.role,
                "balance": float(user.balance),
                "quota": QuotaService.summary(db, user.id),
            }
            for user in users
        ]
    )


@router.post("/set_role")
async def set_role(
    request: SetRoleRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """设置用户角色"""
    AdminService.set_user_role(db, request.user_id, request.role)
    audit(db, current_user, "设置用户角色", "user", request.user_id)
    db.commit()
    return success_response(message="Role updated")


@router.get("/gpu_types")
async def get_gpu_types(
    current_user: User = Depends(get_current_admin_user), db: Session = Depends(get_db)
):
    """获取所有GPU类型"""
    gpu_types = db.query(GPUType).all()
    return success_response(
        data=[
            {
                "code": gpu_type.code,
                "name": gpu_type.name,
                "memory_mb": gpu_type.memory_mb,
            }
            for gpu_type in gpu_types
        ]
    )


@router.post("/create_pool")
async def create_pool(
    request: CreatePoolRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """创建资源池"""
    try:
        pool = AdminService.create_resource_pool(
            db=db,
            name=request.name,
            gpu_type=request.gpu_type,
            node_ids=request.node_ids,
        )
        audit(db, current_user, "创建资源池", "pool", pool.id)
        db.commit()
        return success_response(data={"pool_id": pool.id, "message": "Resource pool created"})
    except ResourceNotFoundError as e:
        return error_response(message=f"资源未找到: {str(e)}")
    except Exception as e:
        import traceback

        traceback.print_exc()
        return error_response(message=f"创建失败: {str(e)}")
