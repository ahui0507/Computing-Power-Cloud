from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.database import Base


def config(connection):
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


def test_migrations_build_current_schema_and_can_roll_back():
    with create_engine("sqlite://").connect() as connection:
        cfg = config(connection)
        command.upgrade(cfg, "head")
        assert set(Base.metadata.tables).issubset(inspect(connection).get_table_names())
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(cfg, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}


def test_migration_normalizes_legacy_uppercase_values():
    with create_engine("sqlite://").connect() as connection:
        cfg = config(connection)
        command.upgrade(cfg, "0001_initial_schema")
        connection.execute(
            text(
                "INSERT INTO nodes (id, hostname, ip, status) "
                "VALUES (1, 'test', '127.0.0.1', 'ONLINE')"
            )
        )
        connection.commit()
        command.upgrade(cfg, "head")
        assert connection.execute(text("SELECT status FROM nodes WHERE id=1")).scalar() == "online"


def test_initialization_seeds_required_roles_and_is_idempotent(monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from scripts import init_db

    with create_engine("sqlite://").connect() as connection:
        cfg = config(connection)
        monkeypatch.setattr(init_db, "Config", lambda path: cfg)
        monkeypatch.setattr(init_db, "SessionLocal", sessionmaker(bind=connection))
        init_db.init_database()
        init_db.init_database()
        assert connection.execute(text("SELECT COUNT(*) FROM roles")).scalar() == 3
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM gpu_types")).scalar() == 4
        assert connection.execute(text("SELECT COUNT(*) FROM billing_rates")).scalar() == 4
        from app.core.security import verify_password, get_password_hash

        assert verify_password(
            __import__("app.core.config", fromlist=["settings"]).settings.INITIAL_ACCOUNT_PASSWORD,
            connection.execute(text("SELECT password_hash FROM users")).scalar()
        )
        personal = get_password_hash("Personal123")
        connection.execute(text("UPDATE users SET password_hash=:value"), {"value": personal})
        connection.commit()
        init_db.init_database()
        assert connection.execute(text("SELECT password_hash FROM users")).scalar() == personal


def test_compute_migration_preserves_legacy_limits_and_blocks_unsafe_downgrade():
    import pytest

    with create_engine("sqlite://").connect() as connection:
        cfg = config(connection)
        command.upgrade(cfg, "0009_prepaid_packages")
        connection.execute(text("INSERT INTO roles (id,name) VALUES (1,'user')"))
        connection.execute(
            text(
                "INSERT INTO users (id,email,password_hash,role_id,balance,status) VALUES (1,'migration@example.com','unused',1,0,'active')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO allocations (id,request_id,user_id,requested_gpu_count,status,billing_mode) VALUES (1,'running',1,1,'active','on_demand'),(2,'old',1,1,'released','on_demand')"
            )
        )
        connection.commit()
        command.upgrade(cfg, "head")
        rows = connection.execute(
            text("SELECT id,cpu_cores,ram_mb,compute_reserved FROM allocations ORDER BY id")
        ).all()
        assert rows == [(1, None, None, 1), (2, None, None, 0)]
        with pytest.raises(RuntimeError, match="CPU/内存预留"):
            command.downgrade(cfg, "0009_prepaid_packages")
        connection.execute(text("UPDATE allocations SET compute_reserved=0"))
        connection.commit()
        command.downgrade(cfg, "0009_prepaid_packages")
        assert "cpu_cores" not in {
            column["name"] for column in inspect(connection).get_columns("allocations")
        }


def test_proportional_migration_preserves_fixed_history_without_inventing_shares():
    import pytest

    with create_engine("sqlite://").connect() as connection:
        cfg = config(connection)
        command.upgrade(cfg, "0010_compute_quotas")
        connection.execute(text("INSERT INTO roles (id,name) VALUES (1,'user')"))
        connection.execute(
            text(
                "INSERT INTO users (id,email,password_hash,role_id,balance,status) VALUES (1,'proportion@example.com','unused',1,17,'active')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO allocations (id,request_id,user_id,requested_gpu_count,status,billing_mode,cpu_cores,ram_mb) VALUES (1,'fixed',1,1,'released','on_demand',3,12345)"
            )
        )
        connection.commit()
        command.upgrade(cfg, "head")
        assert connection.execute(
            text("SELECT cpu_cores,cpu_millicores,ram_mb,node_gpu_count FROM allocations")
        ).one() == (3, 3000, 12345, None)
        assert connection.execute(text("SELECT balance FROM users WHERE id=1")).scalar() == 17
        connection.execute(
            text(
                "INSERT INTO allocations (id,request_id,user_id,requested_gpu_count,status,billing_mode,cpu_millicores,ram_mb,node_gpu_count) VALUES (2,'ratio',1,1,'released','on_demand',1500,10000,4)"
            )
        )
        connection.commit()
        with pytest.raises(RuntimeError, match="比例分配订单"):
            command.downgrade(cfg, "0010_compute_quotas")
