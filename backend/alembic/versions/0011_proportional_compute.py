"""Freeze proportional compute quotas without rewriting old limits."""
from alembic import op
import sqlalchemy as sa

revision = "0011_proportional_compute"
down_revision = "0010_compute_quotas"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("allocations") as batch:
        batch.add_column(sa.Column("cpu_millicores", sa.Integer(), nullable=True, comment="申请时冻结的CPU配额毫核"))
        batch.add_column(sa.Column("node_gpu_count", sa.Integer(), nullable=True, comment="比例分配时冻结的节点GPU总数"))
    op.execute(sa.text("UPDATE allocations SET cpu_millicores=cpu_cores*1000 WHERE cpu_cores IS NOT NULL"))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM allocations WHERE node_gpu_count IS NOT NULL")).scalar():
        raise RuntimeError("已有比例分配订单，不能删除其份额和CPU精度信息")
    with op.batch_alter_table("allocations") as batch:
        batch.drop_column("node_gpu_count")
        batch.drop_column("cpu_millicores")
