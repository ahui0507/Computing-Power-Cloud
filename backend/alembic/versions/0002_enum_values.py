"""Normalize enum values written by older ORM versions to lowercase."""
from alembic import op
import sqlalchemy as sa

revision = "0002_enum_values"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

ENUM_COLUMNS = {
    "allocations": ("status", "billing_mode"),
    "nodes": ("status",),
    "gpus": ("status",),
    "instances": ("status",),
    "images": ("visibility",),
    "billing_rates": ("billing_mode",),
    "billing_records": ("billing_mode",),
    "invoices": ("status",),
    "payments": ("method", "status"),
    "quotas": ("owner_type",),
    "backups": ("backup_type",),
    "users": ("status",),
}


def upgrade():
    for table, columns in ENUM_COLUMNS.items():
        for column in columns:
            # 表名与列名来自固定迁移清单，不接收外部输入。
            op.execute(sa.text(f"UPDATE {table} SET {column} = LOWER({column})"))


def downgrade():
    # 初始基线也使用小写业务值，降级不重新引入历史大写数据。
    pass
