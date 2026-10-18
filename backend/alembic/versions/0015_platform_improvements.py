"""Durable release deadlines, resource queue and account session protection."""
from alembic import op
import sqlalchemy as sa

revision = "0015_platform_improvements"
down_revision = "0014_image_display_name"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("allocations") as batch:
        batch.add_column(sa.Column("release_after_hours", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("scheduled_release_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_allocations_scheduled_release_at", ["scheduled_release_at"]
        )
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "login_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_login_throttles_window_start", "login_throttles", ["window_start"]
    )
    op.create_table(
        "resource_queue",
        sa.Column(
            "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(32), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("container_id", sa.String(100), nullable=True),
        sa.Column("message", sa.String(300), nullable=False),
    )
    for field in ("user_id", "status", "created_at"):
        op.create_index("ix_resource_queue_" + field, "resource_queue", [field])


def downgrade():
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM resource_queue WHERE status IN ('waiting','dispatching')"
        )
    ).scalar():
        raise RuntimeError("请先取消或完成排队申请，再回退")
    if connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM allocations WHERE status IN ('pending','approved','active','releasing') AND (scheduled_release_at IS NOT NULL OR release_after_hours IS NOT NULL)"
        )
    ).scalar():
        raise RuntimeError("请先取消定时释放，再回退")
    op.drop_table("resource_queue")
    op.drop_table("login_throttles")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("auth_version")
    with op.batch_alter_table("allocations") as batch:
        batch.drop_index("ix_allocations_scheduled_release_at")
        batch.drop_column("scheduled_release_at")
        batch.drop_column("release_after_hours")
