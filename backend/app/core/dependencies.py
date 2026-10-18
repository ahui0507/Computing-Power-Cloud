"""访问令牌与用户状态校验。"""
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserStatus

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    invalid = HTTPException(
        401, "Could not validate credentials", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise invalid
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise invalid
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise invalid from exc
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).populate_existing().first()
    if user is None:
        raise invalid
    if payload.get("auth_version", 0) != (user.auth_version or 0):
        raise invalid
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(403, "User is not active")
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(403, "Not enough permissions")
    return current_user
