"""Separate a friendly image label from its immutable runtime reference."""
from alembic import op
import sqlalchemy as sa

revision = "0014_image_display_name"
down_revision = "0013_fixed_storage_quotas"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("display_name", sa.String(128), nullable=True))


def downgrade():
    with op.batch_alter_table("images") as batch:
        batch.drop_column("display_name")
