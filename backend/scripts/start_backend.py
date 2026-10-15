"""容器启动入口：等待数据库，初始化后再启动 API。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine
from app.services.readiness_service import ReadinessService
from scripts.init_db import init_database


def prepare_database(database_engine=engine, initializer=init_database):
    deadline = time.monotonic() + settings.DATABASE_STARTUP_TIMEOUT_SECONDS
    while True:
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("数据库在启动等待时间内不可用") from None
            time.sleep(1)
    if settings.AUTO_INIT_DATABASE:
        initializer()
    with database_engine.connect() as connection:
        readiness = ReadinessService.check(connection)
    if readiness["status"] != "healthy":
        raise RuntimeError(f"数据库尚未就绪: {readiness['database']}")


if __name__ == "__main__":
    prepare_database()
    if "--initialize-only" not in sys.argv:
        uvicorn.run("app.main:app", host=settings.BACKEND_HOST, port=settings.BACKEND_PORT, log_level=settings.LOG_LEVEL.lower())
