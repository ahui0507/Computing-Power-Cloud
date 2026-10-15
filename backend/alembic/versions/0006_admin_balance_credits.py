"""Add atomic, idempotent administrator balance credits."""
from alembic import op
import sqlalchemy as sa

revision = "0006_admin_balance_credits"
down_revision = "0005_monitoring_and_quotas"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "balance_credits",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_before", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 4), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_balance_credits_user_id", "balance_credits", ["user_id"])


def downgrade():
    op.drop_index("ix_balance_credits_user_id", table_name="balance_credits")
    op.drop_table("balance_credits")
