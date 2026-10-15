"""统一响应内容；错误同时保留真实 HTTP 状态码。"""
from typing import Any, Generic, Optional, TypeVar
import math

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None


def success_response(data: Any = None, message: str = "success") -> ApiResponse:
    return ApiResponse(code=200, message=message, data=data)


def error_response(code: int = 400, message: str = "error", data: Any = None, headers=None):
    response = {"code": code, "message": message, "data": data}
    return JSONResponse(
        status_code=code,
        content=jsonable_encoder(
            response,
            custom_encoder={
                Exception: str,
                float: lambda value: value if math.isfinite(value) else None,
            },
        ),
        headers=headers,
    )
