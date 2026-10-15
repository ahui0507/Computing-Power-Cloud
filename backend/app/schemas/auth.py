"""
认证相关Schema
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
import re


class EmailInput(BaseModel):
    """Shared email normalization for all authentication requests."""

    email: str = Field(..., max_length=128, description="邮箱地址")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip()
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, v):
            raise ValueError("Invalid email address")
        return v.lower()  # 转换为小写


class LoginRequest(EmailInput):
    """登录请求"""

    password: str = Field(..., description="密码")


class AuthResponse(BaseModel):
    """认证响应"""

    user_id: int
    token: str
    role: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    """令牌响应"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
