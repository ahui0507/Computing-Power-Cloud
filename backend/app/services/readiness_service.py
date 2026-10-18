"""检查数据库版本和必要初始化数据，而非只确认能建立连接。"""

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text


class ReadinessService:
    @staticmethod
    def check(connection):
        configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        expected = ScriptDirectory.from_config(configuration).get_current_head()
        current = MigrationContext.configure(connection).get_current_revision()
        if current != expected:
            return {"status": "unhealthy", "database": "migration_required"}
        tables = set(inspect(connection).get_table_names())
        required = {
            "users",
            "roles",
            "gpu_types",
            "resource_pools",
            "allocations",
            "instances",
            "allocation_operations",
            "node_metrics",
            "quotas",
            "balance_credits",
            "notices",
            "resource_queue",
            "login_throttles",
        }
        if not required.issubset(tables):
            return {"status": "unhealthy", "database": "schema_incomplete"}
        roles = set(connection.execute(text("SELECT name FROM roles")).scalars())
        if not {"user", "admin"}.issubset(roles):
            return {"status": "unhealthy", "database": "initialization_required"}
        return {"status": "healthy", "database": "ready", "schema_version": current}
