"""Persistent storage shares and deduplicated in-app notices."""

from alembic import op
import sqlalchemy as sa

revision = "0012_storage_and_notices"
down_revision = "0011_proportional_compute"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("quotas") as batch:
        batch.add_column(
            sa.Column(
                "storage_share_percent",
                sa.Float(),
                nullable=True,
                comment="个人存储占用户存储池的比例",
            )
        )
    op.create_table(
        "notices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "allocation_id",
            sa.BigInteger(),
            sa.ForeignKey("allocations.id"),
            nullable=True,
        ),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("link", sa.String(200), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_notices_user_key"),
    )
    op.create_index("ix_notices_id", "notices", ["id"])
    op.create_index("ix_notices_user_id", "notices", ["user_id"])


def downgrade():
    op.drop_index("ix_notices_user_id", table_name="notices")
    op.drop_index("ix_notices_id", table_name="notices")
    op.drop_table("notices")
    with op.batch_alter_table("quotas") as batch:
        batch.drop_column("storage_share_percent")
