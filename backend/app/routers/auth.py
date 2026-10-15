"""
认证路由
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.response import success_response, ApiResponse
from app.core.exceptions import AuthorizationError
from app.core.dependencies import get_current_user
from app.schemas.auth import LoginRequest, AuthResponse
from app.schemas.user import UserInfo
from app.services.auth_service import AuthService
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/send_code", deprecated=True, response_model=ApiResponse)
@router.post("/register", deprecated=True, response_model=ApiResponse)
def registration_closed():
    """Give old clients an explicit result without sending mail or creating users."""
    raise AuthorizationError("自主注册已关闭，请联系管理员创建账号")


@router.post("/login", response_model=ApiResponse[AuthResponse])
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    user = AuthService.authenticate_user(db=db, email=request.email, password=request.password)
    token = AuthService.create_token(user)

    return success_response(data={"user_id": user.id, "token": token, "role": user.role})


@router.get("/user_info", response_model=ApiResponse[UserInfo])
async def get_user_info(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """获取当前用户信息"""
    return success_response(
        data={
            "user_id": current_user.id,
            "email": current_user.email or "",
            "role": current_user.role,
            "balance": float(current_user.balance),
        }
    )
