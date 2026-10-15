"""
容器操作相关Schema
"""
from pydantic import BaseModel, Field


class ContainerOperationRequest(BaseModel):
    """容器操作请求"""

    container_id: str = Field(min_length=1)


class ContainerResizeRequest(BaseModel):
    """容器调整GPU数量请求"""

    container_id: str = Field(min_length=1)
    new_gpu_count: int = Field(gt=0)
