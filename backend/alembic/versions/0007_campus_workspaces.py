"""Persist debt grace periods and personal image save jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0007_campus_workspaces"
down_revision = "0006_admin_balance_credits"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("debt_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("grace_expires_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("supports_ssh", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("snapshot_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("snapshot_status", sa.String(20), nullable=False, server_default="ready"))
        batch.add_column(sa.Column("snapshot_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_node_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("source_container_id", sa.String(255), nullable=True))
        batch.create_foreign_key("fk_image_source_node", "nodes", ["source_node_id"], ["id"])
        batch.create_unique_constraint("uq_image_snapshot", ["snapshot_id"])
    with op.batch_alter_table("images") as batch:
        batch.alter_column("supports_ssh", server_default=None)
        batch.alter_column("snapshot_status", server_default=None)


def downgrade():
    with op.batch_alter_table("images") as batch:
        batch.drop_constraint("uq_image_snapshot", type_="unique")
        batch.drop_constraint("fk_image_source_node", type_="foreignkey")
        for name in ("supports_ssh", "snapshot_id", "snapshot_status", "snapshot_error", "source_node_id", "source_container_id"):
            batch.drop_column(name)
    op.drop_column("users", "grace_expires_at")
    op.drop_column("users", "debt_started_at")
