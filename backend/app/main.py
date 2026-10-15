"""
FastAPI应用主入口
"""

from fastapi import FastAPI
import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.database import engine
from app.core.middleware import LoggingMiddleware
from app.core.exceptions import ComputingPlatformException
from app.core.response import ApiResponse, error_response
from app.services.readiness_service import ReadinessService
from app.services.reconciliation_service import reconciliation_loop
from app.core.exception_handler import (
    validation_exception_handler,
    http_exception_handler,
    computing_platform_exception_handler,
    general_exception_handler,
)
from app.routers import (
    auth,
    resource,
    image,
    container,
    storage,
    billing,
    cluster,
    admin,
)
from app.routers import console, jobs
from app.routers import monitoring
from app.routers import workspace, notices
from app.services.telemetry_service import telemetry_cleanup_loop


# 创建FastAPI应用
@asynccontextmanager
async def lifespan(app):
    stop_event = asyncio.Event()
    task = (
        asyncio.create_task(reconciliation_loop(stop_event))
        if settings.RECONCILIATION_ENABLED
        else None
    )
    telemetry_task = (
        asyncio.create_task(telemetry_cleanup_loop(stop_event))
        if settings.TELEMETRY_CLEANUP_ENABLED
        else None
    )
    try:
        yield
    finally:
        stop_event.set()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if telemetry_task:
            telemetry_task.cancel()
            with suppress(asyncio.CancelledError):
                await telemetry_task


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="算力云平台后端API",
    docs_url="/docs",
    redoc_url="/redoc",
    responses={
        code: {"model": ApiResponse, "description": description}
        for code, description in {
            400: "Invalid operation",
            401: "Authentication required",
            403: "Permission denied",
            404: "Resource not found",
            409: "Resource conflict",
            422: "Request validation failed",
            500: "Internal server error",
            501: "Operation not implemented",
            502: "Cluster operation failed",
            503: "Cluster unavailable",
        }.items()
    },
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加日志中间件
app.add_middleware(LoggingMiddleware)

# 注册异常处理器
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(ComputingPlatformException, computing_platform_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册路由
app.include_router(auth.router)
app.include_router(resource.router)
app.include_router(image.router)
app.include_router(container.router)
app.include_router(storage.router)
app.include_router(billing.router)
app.include_router(cluster.router)
app.include_router(admin.router)
app.include_router(console.router)
app.include_router(jobs.router)
app.include_router(monitoring.router)
app.include_router(notices.router)
app.include_router(workspace.router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Computing Power Cloud Platform API",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """数据库版本、初始化数据和连接就绪检查。"""
    try:
        with engine.connect() as connection:
            result = ReadinessService.check(connection)
    except SQLAlchemyError:
        result = {"status": "unhealthy", "database": "unavailable"}
    if result["status"] != "healthy":
        return error_response(503, "Backend is not ready", result)
    return result


@app.get("/live")
async def liveness():
    return {"status": "alive"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
