"""
存储相关Schema
"""
from pydantic import BaseModel


class DeleteFileRequest(BaseModel):
    """删除文件请求"""
    path: str

