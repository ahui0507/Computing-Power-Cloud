"""Freeze allocation prices and support workload commands and status details."""
from alembic import op
import sqlalchemy as sa

revision = "0003_workload_runtime"
down_revision = "0002_enum_values"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "allocations",
        sa.Column("hourly_price", sa.Numeric(12, 4), nullable=True, comment="申请时确定的单卡小时价格"),
    )
    op.add_column(
        "instances", sa.Column("status_message", sa.String(512), nullable=True, comment="工作负载状态说明")
    )
    op.add_column(
        "images",
        sa.Column(
            "startup_command", sa.String(1024), nullable=True, comment="Jupyter 启动程序路径，空值使用平台默认值"
        ),
    )


def downgrade():
    op.drop_column("images", "startup_command")
    op.drop_column("instances", "status_message")
    op.drop_column("allocations", "hourly_price")
