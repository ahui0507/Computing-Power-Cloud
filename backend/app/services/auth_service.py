"""
认证服务
"""

from datetime import datetime
from sqlalchemy.orm import Session
from app.models.user import User, UserStatus
from app.core.security import verify_password, create_access_token
from app.core.exceptions import (
    AuthenticationError,
    ResourceNotFoundError,
)


class AuthService:
    """认证服务类"""

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> User:
        """验证用户登录"""
        user = db.query(User).filter(User.email == email, User.deleted_at.is_(None)).first()
        if not user:
            raise AuthenticationError("Invalid email or password")

        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")

        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError("User is not active")

        # 更新最后登录时间
        user.last_login = datetime.utcnow()
        db.commit()

        return user

    @staticmethod
    def create_token(user: User) -> str:
        """创建访问令牌"""
        token_data = {
            "sub": str(user.id),  # JWT 标准要求 sub 必须是字符串
            "email": user.email or "",
            "role": user.role,  # 使用property返回角色名称
        }
        return create_access_token(token_data)

    @staticmethod
    def get_user_info(db: Session, user_id: int) -> User:
        """获取用户信息"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ResourceNotFoundError("User")
        return user
