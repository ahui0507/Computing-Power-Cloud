"""Persist resource operation intent, leases and request identity."""
from alembic import op
import sqlalchemy as sa

revision = "0004_recoverable_operations"
down_revision = "0003_workload_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "allocations",
        sa.Column("request_fingerprint", sa.String(64), nullable=True, comment="幂等请求参数摘要"),
    )
    op.add_column(
        "allocations",
        sa.Column(
            "release_requested_at", sa.DateTime(timezone=True), nullable=True, comment="释放请求接收时间"
        ),
    )
    op.add_column(
        "allocations",
        sa.Column(
            "billing_end_time", sa.DateTime(timezone=True), nullable=True, comment="持久化计费截止时间"
        ),
    )
    op.add_column(
        "allocations",
        sa.Column(
            "last_observed_at", sa.DateTime(timezone=True), nullable=True, comment="最后成功观测时间"
        ),
    )
    op.add_column(
        "allocations",
        sa.Column(
            "last_reconciled_at", sa.DateTime(timezone=True), nullable=True, comment="最后后台核对时间"
        ),
    )
    op.add_column(
        "allocations",
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True, comment="首次交互服务就绪时间"),
    )
    op.execute(
        sa.text(
            "UPDATE allocations SET ready_at=COALESCE(start_time, created_at) WHERE status='active'"
        )
    )
    if op.get_context().dialect.name == "mysql":
        # 兼容由历史 SQL 创建的原生 ENUM，新增状态统一使用 VARCHAR。
        op.alter_column(
            "allocations",
            "status",
            existing_type=sa.String(20),
            type_=sa.String(20),
            existing_nullable=False,
        )
    op.create_table(
        "allocation_operations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "allocation_id",
            sa.BigInteger(),
            sa.ForeignKey("allocations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("create", "release", name="operationkind", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                name="operationstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("allocation_id", "kind", name="uq_allocation_operation_kind"),
    )
    op.create_index(
        "ix_allocation_operations_ready",
        "allocation_operations",
        ["status", "retry_at", "lease_until"],
    )


def downgrade():
    op.drop_index("ix_allocation_operations_ready", table_name="allocation_operations")
    op.drop_table("allocation_operations")
    op.execute(sa.text("UPDATE allocations SET status='failed' WHERE status='releasing'"))
    op.drop_column("allocations", "billing_end_time")
    op.drop_column("allocations", "last_observed_at")
    op.drop_column("allocations", "last_reconciled_at")
    op.drop_column("allocations", "ready_at")
    op.drop_column("allocations", "release_requested_at")
    op.drop_column("allocations", "request_fingerprint")
