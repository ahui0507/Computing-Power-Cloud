"""
镜像相关Schema
"""

from pydantic import ConfigDict, BaseModel, Field
from uuid import UUID, uuid4
from typing import Optional
from datetime import datetime


class ImageResponse(BaseModel):
    """镜像响应"""

    image_id: int
    name: str
    display_name: Optional[str] = None
    tag: str
    desc: str
    size: Optional[float] = None
    is_public: Optional[bool] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SaveImageRequest(BaseModel):
    """保存镜像请求"""

    container_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    tag: str = Field(
        default="latest",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$",
    )
    request_id: UUID = Field(default_factory=uuid4)
    desc: str = Field(default="", max_length=500)
