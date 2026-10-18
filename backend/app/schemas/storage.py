"""
存储相关Schema
"""
from pydantic import BaseModel
from typing import Literal


class TrainingExampleRequest(BaseModel):
    framework: Literal["pytorch", "tensorflow"] = "pytorch"


class DeleteFileRequest(BaseModel):
    """删除文件请求"""
    path: str

