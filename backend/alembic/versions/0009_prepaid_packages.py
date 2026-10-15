"""Add fixed day/week purchases and readable instance names."""
from datetime import timezone
from zoneinfo import ZoneInfo
import re

from alembic import op
import sqlalchemy as sa

revision = "0009_prepaid_packages"
down_revision = "0008_personal_image_history"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("allocations") as batch:
        batch.alter_column("billing_mode", existing_type=sa.String(20), type_=sa.String(20), existing_nullable=False, comment="计费模式")
        batch.add_column(sa.Column("package_amount", sa.Numeric(14, 4), nullable=True, comment="包日/包周购买时冻结的总价"))
        for name in ("package_paid_at", "package_expires_at", "package_refunded_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for table in ("billing_records", "billing_rates"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("billing_mode", existing_type=sa.String(20), type_=sa.String(20), existing_nullable=False, comment="计费模式")
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT i.id,i.instance_name,a.user_id,a.created_at,g.code FROM instances i JOIN allocations a ON i.allocation_id=a.id LEFT JOIN gpu_types g ON a.gpu_type_id=g.id ORDER BY a.id")).mappings().all()
    used = {(row["user_id"], row["instance_name"]) for row in rows if not row["instance_name"].startswith("container-")}
    from datetime import datetime
    for row in rows:
        if not row["instance_name"].startswith("container-"):
            continue
        created = row["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        code = re.sub(r"[^A-Za-z0-9.-]", "", row["code"] or "GPU") or "GPU"
        base = code + "-" + created.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%y%m%d%H%M")
        name, suffix = base, 2
        while (row["user_id"], name) in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add((row["user_id"], name))
        connection.execute(sa.text("UPDATE instances SET instance_name=:name WHERE id=:id"), {"name": name, "id": row["id"]})


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM allocations WHERE package_paid_at IS NOT NULL")).scalar():
        raise RuntimeError("已有包日/包周订单，不支持删除其支付和到期信息")
    with op.batch_alter_table("allocations") as batch:
        for name in ("package_refunded_at", "package_expires_at", "package_paid_at", "package_amount"):
            batch.drop_column(name)
