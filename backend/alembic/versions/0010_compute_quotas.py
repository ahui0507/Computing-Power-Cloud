"""Reserve CPU and memory together with GPU allocations."""
from alembic import op
import sqlalchemy as sa

revision = "0010_compute_quotas"
down_revision = "0009_prepaid_packages"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("allocations") as batch:
        batch.add_column(sa.Column("cpu_cores", sa.Integer(), nullable=True, comment="申请时冻结的CPU逻辑核心配额"))
        batch.add_column(sa.Column("ram_mb", sa.BigInteger(), nullable=True, comment="申请时冻结的内存配额MiB"))
        batch.add_column(sa.Column("compute_reserved", sa.Boolean(), nullable=False, server_default=sa.false(), comment="CPU和内存仍被预留"))
    # Old running pods have no CPU/RAM limits. Keep them running, but block new
    # reservations on their node until they are released rather than invent limits.
    op.execute(sa.text("UPDATE allocations SET compute_reserved=1 WHERE status IN ('pending','approved','active','releasing') OR id IN (SELECT allocation_id FROM gpus WHERE allocation_id IS NOT NULL)"))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM allocations WHERE compute_reserved=1")).scalar():
        raise RuntimeError("仍有CPU/内存预留，请先完成实例回收再降级")
    with op.batch_alter_table("allocations") as batch:
        for name in ("compute_reserved", "ram_mb", "cpu_cores"):
            batch.drop_column(name)
