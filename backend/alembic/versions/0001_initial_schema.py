"""Initial platform schema frozen from the reviewed ORM models."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gpu_types",
        sa.Column("id", sa.Integer(), nullable=False, comment="GPU类型ID"),
        sa.Column(
            "code", sa.String(length=32), nullable=False, comment="GPU代码，如K80, V100, A100, RTX4090"
        ),
        sa.Column("name", sa.String(length=64), nullable=False, comment="GPU名称"),
        sa.Column("memory_mb", sa.Integer(), nullable=True, comment="显存MB"),
        sa.Column("compute_capability", sa.String(length=16), nullable=True, comment="计算能力"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_gpu_types_id"), "gpu_types", ["id"], unique=False)
    op.create_table(
        "nodes",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="节点ID"),
        sa.Column("hostname", sa.String(length=128), nullable=False, comment="主机名"),
        sa.Column("ip", sa.String(length=64), nullable=False, comment="IP地址"),
        sa.Column("cpu_cores", sa.Integer(), nullable=True, comment="CPU核心数"),
        sa.Column("memory_gb", sa.Float(), nullable=True, comment="内存GB"),
        sa.Column("gpus_total", sa.Integer(), nullable=True, comment="总GPU数"),
        sa.Column("gpus_free", sa.Integer(), nullable=True, comment="空闲GPU数"),
        sa.Column("cpu_usage", sa.Float(), nullable=True, comment="CPU使用率"),
        sa.Column("mem_usage", sa.Float(), nullable=True, comment="内存使用率"),
        sa.Column("labels", sa.JSON(), nullable=True, comment="标签（JSON格式）"),
        sa.Column(
            "status",
            sa.Enum(
                "online",
                "offline",
                "draining",
                "maintenance",
                name="nodestatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True, comment="最后心跳时间"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hostname"),
    )
    op.create_index(op.f("ix_nodes_id"), "nodes", ["id"], unique=False)
    op.create_table(
        "quotas",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="配额ID"),
        sa.Column(
            "owner_type",
            sa.Enum("user", "project", name="ownertype", native_enum=False, length=20),
            nullable=False,
            comment="所有者类型",
        ),
        sa.Column("owner_id", sa.BigInteger(), nullable=False, comment="所有者ID"),
        sa.Column("max_gpus", sa.Integer(), nullable=False, comment="最大GPU数"),
        sa.Column("max_instances", sa.Integer(), nullable=False, comment="最大实例数"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quotas_id"), "quotas", ["id"], unique=False)
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False, comment="角色ID"),
        sa.Column("name", sa.String(length=32), nullable=False, comment="角色名称"),
        sa.Column("description", sa.String(length=255), nullable=True, comment="角色描述"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_roles_id"), "roles", ["id"], unique=False)
    op.create_table(
        "settings",
        sa.Column("k", sa.String(length=128), nullable=False, comment="配置键"),
        sa.Column("v", sa.Text(), nullable=True, comment="配置值"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="描述"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("k"),
    )
    op.create_table(
        "resource_pools",
        sa.Column("id", sa.Integer(), nullable=False, comment="资源池ID"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="资源池名称"),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False, comment="GPU类型ID"),
        sa.Column("node_ids", sa.JSON(), nullable=False, comment="节点ID列表（JSON数组）"),
        sa.Column("total_gpus", sa.Integer(), nullable=True, comment="总GPU数"),
        sa.Column("free_gpus", sa.Integer(), nullable=True, comment="空闲GPU数"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="描述"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["gpu_type_id"],
            ["gpu_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_resource_pools_id"), "resource_pools", ["id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("username", sa.String(length=64), nullable=True, comment="用户名"),
        sa.Column("email", sa.String(length=128), nullable=True, comment="邮箱"),
        sa.Column("phone", sa.String(length=32), nullable=True, comment="手机号"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码哈希"),
        sa.Column("role_id", sa.Integer(), nullable=False, comment="角色ID，默认2=user"),
        sa.Column("balance", sa.Numeric(precision=12, scale=4), nullable=False, comment="余额"),
        sa.Column(
            "status",
            sa.Enum(
                "active", "disabled", "banned", name="userstatus", native_enum=False, length=20
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True, comment="最后登录时间"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, comment="软删除时间"),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=True)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="日志ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="用户ID"),
        sa.Column("action", sa.String(length=128), nullable=False, comment="操作类型"),
        sa.Column("resource_type", sa.String(length=64), nullable=True, comment="资源类型"),
        sa.Column("resource_id", sa.String(length=64), nullable=True, comment="资源ID"),
        sa.Column("detail", sa.JSON(), nullable=True, comment="详细信息（JSON格式）"),
        sa.Column("ip_address", sa.String(length=64), nullable=True, comment="IP地址"),
        sa.Column("user_agent", sa.String(length=500), nullable=True, comment="User Agent"),
        sa.Column("result", sa.String(length=50), nullable=False, comment="结果（success/failed）"),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="时间戳",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_table(
        "billing_rates",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="费率ID"),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False, comment="GPU类型ID"),
        sa.Column(
            "billing_mode",
            sa.Enum("hour", "week", "month", name="billingmode", native_enum=False, length=20),
            nullable=False,
            comment="计费模式",
        ),
        sa.Column(
            "price", sa.Numeric(precision=12, scale=4), nullable=False, comment="价格，单位：货币/（小时|周|月）"
        ),
        sa.Column("currency", sa.String(length=8), nullable=False, comment="货币"),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="生效开始时间",
        ),
        sa.Column(
            "effective_to", sa.DateTime(timezone=True), nullable=True, comment="生效结束时间，NULL表示一直有效"
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="创建者ID"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["gpu_type_id"],
            ["gpu_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_billing_rates_id"), "billing_rates", ["id"], unique=False)
    op.create_table(
        "images",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="镜像ID"),
        sa.Column("name", sa.String(length=255), nullable=False, comment="镜像名称"),
        sa.Column("tag", sa.String(length=100), nullable=False, comment="标签"),
        sa.Column("repo", sa.String(length=500), nullable=True, comment="仓库地址"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("size", sa.Numeric(precision=12, scale=2), nullable=True, comment="大小GB"),
        sa.Column(
            "visibility",
            sa.Enum("public", "private", name="imagevisibility", native_enum=False, length=20),
            nullable=False,
            comment="可见性",
        ),
        sa.Column("owner_id", sa.BigInteger(), nullable=True, comment="所有者ID，NULL表示公共镜像"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_images_id"), "images", ["id"], unique=False)
    op.create_table(
        "invoices",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="发票ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("invoice_no", sa.String(length=64), nullable=False, comment="发票号"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False, comment="周期开始"),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False, comment="周期结束"),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=4), nullable=False, comment="总金额"),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "paid", "cancelled", name="invoicestatus", native_enum=False, length=20
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="开具时间",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True, comment="支付时间"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_no"),
    )
    op.create_index(op.f("ix_invoices_id"), "invoices", ["id"], unique=False)
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="项目ID"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="项目名称"),
        sa.Column("owner_id", sa.BigInteger(), nullable=False, comment="所有者ID"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_id"), "projects", ["id"], unique=False)
    op.create_table(
        "ssh_keys",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="密钥ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="密钥名称"),
        sa.Column("public_key", sa.Text(), nullable=False, comment="公钥内容"),
        sa.Column("fingerprint", sa.String(length=128), nullable=True, comment="指纹"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ssh_keys_id"), "ssh_keys", ["id"], unique=False)
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("full_name", sa.String(length=128), nullable=True, comment="全名"),
        sa.Column("organization", sa.String(length=128), nullable=True, comment="组织"),
        sa.Column("avatar_url", sa.String(length=255), nullable=True, comment="头像URL"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "allocations",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="分配ID"),
        sa.Column("request_id", sa.String(length=64), nullable=False, comment="请求ID，前端或调度流水号"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("project_id", sa.BigInteger(), nullable=True, comment="项目ID"),
        sa.Column("pool_id", sa.Integer(), nullable=True, comment="资源池ID"),
        sa.Column("requested_gpu_count", sa.Integer(), nullable=False, comment="请求的GPU数量"),
        sa.Column("gpu_type_id", sa.Integer(), nullable=True, comment="用户优先选择的GPU类型"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "active",
                "stopped",
                "released",
                "failed",
                name="allocationstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column(
            "billing_mode",
            sa.Enum(
                "on_demand",
                "prepaid",
                "hour",
                "week",
                "month",
                name="billingmode",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="计费模式",
        ),
        sa.Column("image_id", sa.BigInteger(), nullable=True, comment="镜像ID"),
        sa.Column("image_name", sa.String(length=200), nullable=True, comment="镜像名称（冗余）"),
        sa.Column("node_id", sa.BigInteger(), nullable=True, comment="分配的节点ID"),
        sa.Column("gpu_ids", sa.JSON(), nullable=True, comment="分配的GPU ID列表"),
        sa.Column("container_id", sa.String(length=100), nullable=True, comment="容器ID"),
        sa.Column("pod_name", sa.String(length=200), nullable=True, comment="K8s Pod名称"),
        sa.Column("ssh_port", sa.Integer(), nullable=True, comment="SSH端口"),
        sa.Column("vnc_port", sa.Integer(), nullable=True, comment="VNC端口"),
        sa.Column("jupyter_port", sa.Integer(), nullable=True, comment="Jupyter端口"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True, comment="开始时间"),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True, comment="结束时间"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["gpu_type_id"],
            ["gpu_types.id"],
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["resource_pools.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("container_id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(op.f("ix_allocations_id"), "allocations", ["id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="支付ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("invoice_id", sa.BigInteger(), nullable=True, comment="发票ID"),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=False, comment="金额"),
        sa.Column(
            "method",
            sa.Enum(
                "balance",
                "alipay",
                "wechat",
                "bank",
                "other",
                name="paymentmethod",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="支付方式",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "initiated", "success", "failed", name="paymentstatus", native_enum=False, length=20
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True, comment="支付时间"),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_id"), "payments", ["id"], unique=False)
    op.create_table(
        "gpus",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="GPU ID"),
        sa.Column("node_id", sa.BigInteger(), nullable=False, comment="节点ID"),
        sa.Column("gpu_index", sa.Integer(), nullable=False, comment="GPU索引，如0,1..."),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False, comment="GPU类型ID"),
        sa.Column("uuid", sa.String(length=100), nullable=True, comment="GPU UUID"),
        sa.Column("memory_gb", sa.Float(), nullable=True, comment="显存GB"),
        sa.Column(
            "status",
            sa.Enum(
                "free",
                "reserved",
                "occupied",
                "maintenance",
                name="gpustatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column("occupied_by", sa.BigInteger(), nullable=True, comment="被哪个用户占用"),
        sa.Column("allocation_id", sa.BigInteger(), nullable=True, comment="被哪个分配占用"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["allocations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["gpu_type_id"],
            ["gpu_types.id"],
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["occupied_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(op.f("ix_gpus_id"), "gpus", ["id"], unique=False)
    op.create_table(
        "instances",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="实例ID"),
        sa.Column("allocation_id", sa.BigInteger(), nullable=False, comment="分配ID"),
        sa.Column("instance_name", sa.String(length=128), nullable=False, comment="实例名称"),
        sa.Column("node_id", sa.BigInteger(), nullable=False, comment="所在节点"),
        sa.Column("gpu_ids", sa.JSON(), nullable=True, comment="GPU ID列表"),
        sa.Column("image_id", sa.BigInteger(), nullable=False, comment="镜像ID"),
        sa.Column("ssh_port", sa.Integer(), nullable=True, comment="SSH端口"),
        sa.Column("vnc_port", sa.Integer(), nullable=True, comment="VNC端口"),
        sa.Column("jupyter_port", sa.Integer(), nullable=True, comment="Jupyter端口"),
        sa.Column(
            "status",
            sa.Enum(
                "creating",
                "running",
                "stopped",
                "terminated",
                "error",
                name="instancestatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
            comment="状态",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, comment="启动时间"),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True, comment="停止时间"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["allocations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_instances_id"), "instances", ["id"], unique=False)
    op.create_table(
        "backups",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="备份ID"),
        sa.Column("instance_id", sa.BigInteger(), nullable=True, comment="实例ID"),
        sa.Column("backup_path", sa.String(length=512), nullable=True, comment="备份路径"),
        sa.Column("backup_size", sa.BigInteger(), nullable=True, comment="备份大小（字节）"),
        sa.Column(
            "backup_type",
            sa.Enum("snapshot", "image", "data", name="backuptype", native_enum=False, length=20),
            nullable=False,
            comment="备份类型",
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="创建者ID"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backups_id"), "backups", ["id"], unique=False)
    op.create_table(
        "billing_records",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="记录ID"),
        sa.Column("instance_id", sa.BigInteger(), nullable=True, comment="实例ID"),
        sa.Column("allocation_id", sa.BigInteger(), nullable=True, comment="分配ID（冗余）"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("gpu_type_id", sa.Integer(), nullable=False, comment="GPU类型ID"),
        sa.Column("gpu_count", sa.Integer(), nullable=False, comment="GPU数量"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False, comment="开始时间"),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False, comment="结束时间"),
        sa.Column("minutes", sa.Integer(), nullable=False, comment="使用时长（分钟）"),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
            comment="单位价格，结算时从billing_rates复制",
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=14, scale=4),
            nullable=False,
            comment="金额 = unit_price * factor",
        ),
        sa.Column(
            "billing_mode",
            sa.Enum("hour", "week", "month", name="billingmode", native_enum=False, length=20),
            nullable=False,
            comment="计费模式",
        ),
        sa.Column("settled", sa.Boolean(), nullable=False, comment="是否已结算"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["allocations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["gpu_type_id"],
            ["gpu_types.id"],
        ),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["instances.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_billing_records_id"), "billing_records", ["id"], unique=False)
    op.create_table(
        "invoice_items",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="明细ID"),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False, comment="发票ID"),
        sa.Column("billing_record_id", sa.BigInteger(), nullable=False, comment="计费记录ID"),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=False, comment="金额"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["billing_record_id"],
            ["billing_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_invoice_items_id"), "invoice_items", ["id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_invoice_items_id"), table_name="invoice_items")
    op.drop_table("invoice_items")
    op.drop_index(op.f("ix_billing_records_id"), table_name="billing_records")
    op.drop_table("billing_records")
    op.drop_index(op.f("ix_backups_id"), table_name="backups")
    op.drop_table("backups")
    op.drop_index(op.f("ix_instances_id"), table_name="instances")
    op.drop_table("instances")
    op.drop_index(op.f("ix_gpus_id"), table_name="gpus")
    op.drop_table("gpus")
    op.drop_index(op.f("ix_payments_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_allocations_id"), table_name="allocations")
    op.drop_table("allocations")
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_ssh_keys_id"), table_name="ssh_keys")
    op.drop_table("ssh_keys")
    op.drop_index(op.f("ix_projects_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_invoices_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(op.f("ix_images_id"), table_name="images")
    op.drop_table("images")
    op.drop_index(op.f("ix_billing_rates_id"), table_name="billing_rates")
    op.drop_table("billing_rates")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_users_phone"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_resource_pools_id"), table_name="resource_pools")
    op.drop_table("resource_pools")
    op.drop_table("settings")
    op.drop_index(op.f("ix_roles_id"), table_name="roles")
    op.drop_table("roles")
    op.drop_index(op.f("ix_quotas_id"), table_name="quotas")
    op.drop_table("quotas")
    op.drop_index(op.f("ix_nodes_id"), table_name="nodes")
    op.drop_table("nodes")
    op.drop_index(op.f("ix_gpu_types_id"), table_name="gpu_types")
    op.drop_table("gpu_types")
