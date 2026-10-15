"""
用户相关Schema
"""

from pydantic import ConfigDict, BaseModel
from typing import Optional
from datetime import datetime


class UserInfo(BaseModel):
    """用户信息"""

    user_id: int
    email: str
    role: str
    balance: float
    phone: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
