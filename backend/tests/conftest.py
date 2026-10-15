"""测试只使用内存数据库和替代集群客户端，不连接部署环境。"""
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///unused-test.db"
os.environ["PLATFORM_ENV_FILE"] = ""
os.environ["SECRET_KEY"] = "isolated-test-secret-at-least-32-characters"
os.environ["INITIAL_ACCOUNT_PASSWORD"] = "fixture-initial-account-secret"
os.environ["STORAGE_QUOTA_MODE"] = "percent"
os.environ["INITIAL_ADMIN_EMAIL"] = "fixture-admin@example.com"
os.environ["RECONCILIATION_ENABLED"] = "false"
os.environ["TELEMETRY_CLEANUP_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.config import settings
from app.models import (
    GPU,
    GPUStatus,
    GPUType,
    Image,
    ImageVisibility,
    Node,
    NodeStatus,
    ResourcePool,
    Role,
    User,
    UserStatus,
)


@compiles(BigInteger, "sqlite")
def sqlite_big_integer(type_, compiler, **kwargs):
    # SQLite 自增主键要求类型名称为 INTEGER；MySQL 继续使用 BIGINT。
    return "INTEGER"


@pytest.fixture(autouse=True)
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(tmp_path / "workspaces"))
    if hasattr(os, "getgid"):
        monkeypatch.setattr(settings, "WORKSPACE_GID", os.getgid())
    return tmp_path / "workspaces"


@pytest.fixture
def isolated_workspace(workspace):
    return workspace


@pytest.fixture
def db(isolated_workspace):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    session.add_all(
        [
            Role(id=1, name="admin"),
            Role(id=2, name="user"),
            User(
                id=1,
                email="owner@example.com",
                role_id=2,
                password_hash="unused",
                balance=100,
                status=UserStatus.ACTIVE,
            ),
            User(
                id=2,
                email="other@example.com",
                balance=100,
                role_id=2,
                password_hash="unused",
                status=UserStatus.ACTIVE,
            ),
            GPUType(id=1, code="K80", name="Tesla K80", memory_mb=12288),
            Node(
                id=1,
                hostname="worker-a",
                ip="192.0.2.1",
                status=NodeStatus.ONLINE,
                gpus_total=2,
                gpus_free=2,
                cpu_cores=24,
                memory_gb=128,
            ),
            Image(id=1, name="test-jupyter", tag="v1", visibility=ImageVisibility.PUBLIC),
            Image(
                id=2,
                name="private-jupyter",
                tag="v1",
                visibility=ImageVisibility.PRIVATE,
                owner_id=2,
            ),
            ResourcePool(
                id=1, name="K80 pool", gpu_type_id=1, node_ids=[1], total_gpus=2, free_gpus=2
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            GPU(id=i, node_id=1, gpu_index=i - 1, gpu_type_id=1, status=GPUStatus.FREE)
            for i in (1, 2)
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
