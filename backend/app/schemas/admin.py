"""
管理员相关Schema
"""

from decimal import Decimal
from uuid import UUID
from pydantic import ConfigDict, BaseModel, Field, field_validator
from typing import List
from app.schemas.auth import EmailInput


class UserInfo(BaseModel):
    """用户信息（管理员视图）"""

    user_id: int
    email: str
    role: str
    balance: float

    model_config = ConfigDict(from_attributes=True)


class CreateUserRequest(EmailInput):
    """Administrators create ordinary accounts with the platform's initial password."""

    model_config = ConfigDict(extra="forbid")


class SetRoleRequest(BaseModel):
    """设置角色请求"""

    user_id: int
    role: str  # user, admin


class AddBalanceRequest(BaseModel):
    request_id: UUID
    amount: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=4, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class CreatePoolRequest(BaseModel):
    """创建资源池请求"""

    name: str
    gpu_type: str
    node_ids: List[int]


class CreatePoolResponse(BaseModel):
    """创建资源池响应"""

    pool_id: int
    message: str
