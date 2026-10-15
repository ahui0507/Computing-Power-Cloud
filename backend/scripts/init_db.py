"""升级数据库并幂等创建启动所需的数据；MySQL 上串行执行初始化。"""

import hashlib
import sys
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.security import get_password_hash, INITIAL_ACCOUNT_PASSWORD
from app.models import (
    User,
    UserStatus,
    Role,
    GPUType,
    BillingRate,
    BillingMode,
    Image,
    ImageVisibility,
)


@contextmanager
def initialization_connection(configuration):
    supplied = configuration.attributes.get("connection")
    if supplied is not None:
        yield supplied
        return
    with engine.connect() as connection:
        lock_name = (
            "platform-schema-"
            + hashlib.sha256((engine.url.database or "").encode("utf-8")).hexdigest()[:32]
        )
        locked = False
        try:
            if connection.dialect.name == "mysql":
                locked = (
                    connection.execute(
                        text("SELECT GET_LOCK(:name, :timeout)"),
                        {"name": lock_name, "timeout": settings.DATABASE_STARTUP_TIMEOUT_SECONDS},
                    ).scalar()
                    == 1
                )
                connection.commit()
                if not locked:
                    raise RuntimeError("无法获取数据库初始化锁")
            yield connection
        finally:
            if locked:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
                connection.commit()


def seed_database():
    with SessionLocal() as db:
        try:
            for role_id, name in ((1, "admin"), (2, "user"), (3, "auditor")):
                if not db.query(Role).filter(Role.name == name).first():
                    db.add(Role(id=role_id, name=name, description=name))
            db.flush()
            for code, name, memory_mb in (
                ("K80", "Tesla K80", 12288),
                ("V100", "Tesla V100", 16384),
                ("A100", "NVIDIA A100", 40960),
                ("RTX4090", "GeForce RTX 4090", 24576),
            ):
                if not db.query(GPUType).filter(GPUType.code == code).first():
                    db.add(GPUType(code=code, name=name, memory_mb=memory_mb))
            db.flush()
            admin = db.query(User).filter(User.email == settings.INITIAL_ADMIN_EMAIL).first()
            if admin is None:
                admin_role = db.query(Role).filter(Role.name == "admin").one()
                admin = User(
                    username=settings.INITIAL_ADMIN_USERNAME or None,
                    storage_default_bytes=(settings.DEFAULT_STORAGE_LIMIT_GIB * 1024**3
                                           if settings.STORAGE_QUOTA_MODE == "fixed" else None),
                    email=settings.INITIAL_ADMIN_EMAIL,
                    role_id=admin_role.id,
                    password_hash=get_password_hash(INITIAL_ACCOUNT_PASSWORD),
                    balance=10000,
                    status=UserStatus.ACTIVE,
                )
                db.add(admin)
                db.flush()
            prices = {
                "K80": settings.DEFAULT_GPU_PRICE_K80,
                "V100": settings.DEFAULT_GPU_PRICE_V100,
                "A100": settings.DEFAULT_GPU_PRICE_A100,
                "RTX4090": settings.DEFAULT_GPU_PRICE_RTX4090,
            }
            for gpu_type in db.query(GPUType).all():
                if (
                    not db.query(BillingRate)
                    .filter(
                        BillingRate.gpu_type_id == gpu_type.id,
                        BillingRate.billing_mode == BillingMode.HOUR,
                    )
                    .first()
                ):
                    db.add(
                        BillingRate(
                            gpu_type_id=gpu_type.id,
                            billing_mode=BillingMode.HOUR,
                            price=prices.get(gpu_type.code, 10),
                            effective_from=datetime.utcnow(),
                            created_by=admin.id,
                        )
                    )
            # 默认目录只登记仓库中可构建的 Jupyter 环境，不登记缺少 Jupyter 的基础镜像。
            name, tag = "docker.io/library/jupyter-test", "latest"
            if not db.query(Image).filter(Image.name == name, Image.tag == tag).first():
                db.add(
                    Image(
                        name=name,
                        tag=tag,
                        desc="平台 Jupyter 测试环境",
                        startup_command="jupyter-lab",
                        visibility=ImageVisibility.PUBLIC,
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            raise


def init_database():
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with initialization_connection(configuration) as connection:
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")
        connection.commit()
        seed_database()
    print("Database migration and initialization completed.")


if __name__ == "__main__":
    init_database()
