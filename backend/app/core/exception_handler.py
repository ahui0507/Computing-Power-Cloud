"""异常只在 HTTP 边界转换，服务层保留异常语义。"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.core.exceptions import ComputingPlatformException
from app.core.response import error_response

logger = logging.getLogger(__name__)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(422, "Validation error", {"errors": exc.errors()})


async def http_exception_handler(request: Request, exc: HTTPException):
    return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def computing_platform_exception_handler(request: Request, exc: ComputingPlatformException):
    return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API error: %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "Internal server error")
