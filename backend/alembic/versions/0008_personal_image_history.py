"""Allow historical instances to remain after a personal image is deleted."""
from alembic import op
import sqlalchemy as sa

revision = "0008_personal_image_history"
down_revision = "0007_campus_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("instances") as batch:
        batch.alter_column("image_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM instances WHERE image_id IS NULL")).scalar():
        raise RuntimeError("历史实例的镜像已删除，请恢复关联后再降级")
    with op.batch_alter_table("instances") as batch:
        batch.alter_column("image_id", existing_type=sa.BigInteger(), nullable=False)
