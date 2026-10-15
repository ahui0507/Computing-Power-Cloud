"""Fixed personal limits preserve existing allocations when defaults change."""
from alembic import op
import sqlalchemy as sa

revision = "0013_fixed_storage_quotas"
down_revision = "0012_storage_and_notices"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("storage_default_bytes", sa.BigInteger(), nullable=True))
    with op.batch_alter_table("quotas") as batch:
        batch.add_column(sa.Column("storage_limit_bytes", sa.BigInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("quotas") as batch:
        batch.drop_column("storage_limit_bytes")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("storage_default_bytes")
