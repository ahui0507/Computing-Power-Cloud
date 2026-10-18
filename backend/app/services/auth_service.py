"""
认证服务
"""

from datetime import datetime, timedelta
import hashlib
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models.platform_improvements import LoginThrottle
from app.core.config import settings
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
        now = datetime.utcnow()
        key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        # A row lock serializes failures across backend processes. Never store passwords or emails here.
        throttle = None
        for _ in range(3):
            try:
                with db.begin_nested():
                    throttle = (
                        db.query(LoginThrottle)
                        .filter_by(key=key)
                        .populate_existing()
                        .with_for_update()
                        .first()
                    )
                    if throttle is None:
                        throttle = LoginThrottle(key=key, failures=0, window_start=now)
                        db.add(throttle)
                        db.flush()
                break
            except IntegrityError:
                throttle = None
        if throttle is None:
            db.rollback()
            raise HTTPException(503, "登录服务繁忙，请稍后重试")
        if now - throttle.window_start >= timedelta(
            seconds=settings.LOGIN_WINDOW_SECONDS
        ):
            throttle.failures, throttle.window_start = 0, now
        if throttle.failures >= settings.LOGIN_MAX_FAILURES:
            remaining = max(
                1,
                int(
                    settings.LOGIN_WINDOW_SECONDS
                    - (now - throttle.window_start).total_seconds()
                ),
            )
            db.rollback()
            raise HTTPException(
                429, "登录失败次数过多，请稍后重试", headers={"Retry-After": str(remaining)}
            )
        user = (
            db.query(User)
            .filter(User.email == email, User.deleted_at.is_(None))
            .populate_existing()
            .first()
        )
        if (
            not user
            or not verify_password(password, user.password_hash)
            or user.status != UserStatus.ACTIVE
        ):
            throttle.failures += 1
            db.commit()
            raise AuthenticationError("Invalid email or password")
        throttle.failures = 0
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
            "auth_version": user.auth_version or 0,
        }
        return create_access_token(token_data)

    @staticmethod
    def get_user_info(db: Session, user_id: int) -> User:
        """获取用户信息"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ResourceNotFoundError("User")
        return user
