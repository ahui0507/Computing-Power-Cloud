"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator

from app.core.config import settings

# 创建数据库引擎
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_pre_ping=True,
    # 每条配额/预算查询看到之前已提交的申请；用户行锁串行化同账户申请。
    isolation_level="READ COMMITTED" if settings.DATABASE_URL.startswith("mysql") else None,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    connect_args={"init_command": "SET time_zone = '+00:00'"}
    if settings.DATABASE_URL.startswith("mysql+pymysql:")
    else {},
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

# 创建基础模型类
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话
    使用依赖注入，在请求结束时自动关闭会话
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
