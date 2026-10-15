"""Persist node telemetry and unique per-owner resource limits."""
from alembic import op
import sqlalchemy as sa

revision = "0005_monitoring_and_quotas"
down_revision = "0004_recoverable_operations"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate = connection.execute(sa.text(
        "SELECT owner_type, owner_id FROM quotas GROUP BY owner_type, owner_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("配额表存在重复所有者，请合并重复记录后重新迁移")
    with op.batch_alter_table("quotas") as batch:
        batch.add_column(sa.Column("low_balance_amount", sa.Numeric(12, 4), nullable=False, server_default="10"))
        batch.add_column(sa.Column("low_balance_minutes", sa.Integer(), nullable=False, server_default="30"))
        batch.create_unique_constraint("uq_quotas_owner", ["owner_type", "owner_id"])
    # 默认值仅用于升级既有记录，与 ORM 的客户端默认值保持一致。
    with op.batch_alter_table("quotas") as batch:
        batch.alter_column("low_balance_amount", server_default=None)
        batch.alter_column("low_balance_minutes", server_default=None)
    op.add_column("nodes", sa.Column("monitor_token_hash", sa.String(64), nullable=True))
    op.create_table("node_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_usage", sa.Float(), nullable=True),
        sa.Column("mem_usage", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_node_metrics_node_received", "node_metrics", ["node_id", "received_at"])


def downgrade():
    op.drop_index("ix_node_metrics_node_received", table_name="node_metrics")
    op.drop_table("node_metrics")
    op.drop_column("nodes", "monitor_token_hash")
    with op.batch_alter_table("quotas") as batch:
        batch.drop_constraint("uq_quotas_owner", type_="unique")
        batch.drop_column("low_balance_amount")
        batch.drop_column("low_balance_minutes")
