-- 算力云平台数据库Schema
-- 基于数据库设计文档生成
-- 执行前请确保MySQL已安装并运行

-- 创建数据库
CREATE DATABASE IF NOT EXISTS computing_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE computing_platform;

-- ============================================
-- 1. 角色表
-- ============================================
CREATE TABLE IF NOT EXISTS roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE COMMENT '角色名称，如admin, user',
    description VARCHAR(255) COMMENT '角色描述',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认角色
INSERT IGNORE INTO roles (name, description) VALUES
('admin', '管理员'),
('user', '普通用户'),
('auditor', '审计员');

-- ============================================
-- 2. 用户表
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NULL UNIQUE COMMENT '用户名',
    email VARCHAR(128) NULL UNIQUE COMMENT '邮箱',
    phone VARCHAR(32) NULL UNIQUE COMMENT '手机号',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    role_id INT NOT NULL DEFAULT 2 COMMENT '角色ID，默认2=user',
    balance DECIMAL(12,4) NOT NULL DEFAULT 0.0000 COMMENT '余额',
    status ENUM('active','disabled','banned') DEFAULT 'active' COMMENT '状态',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    last_login DATETIME(6) NULL COMMENT '最后登录时间',
    deleted_at DATETIME(6) NULL COMMENT '软删除时间',
    FOREIGN KEY (role_id) REFERENCES roles(id),
    INDEX idx_phone (phone),
    INDEX idx_email (email),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 3. 用户详情表
-- ============================================
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGINT PRIMARY KEY,
    full_name VARCHAR(128) COMMENT '全名',
    organization VARCHAR(128) COMMENT '组织',
    avatar_url VARCHAR(255) COMMENT '头像URL',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 4. SSH密钥表
-- ============================================
CREATE TABLE IF NOT EXISTS ssh_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(128) NOT NULL COMMENT '密钥名称',
    public_key TEXT NOT NULL COMMENT '公钥内容',
    fingerprint VARCHAR(128) COMMENT '指纹',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 5. 项目表（可选，用于团队/课题）
-- ============================================
CREATE TABLE IF NOT EXISTS projects (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL COMMENT '项目名称',
    owner_id BIGINT NOT NULL COMMENT '所有者ID',
    description TEXT COMMENT '描述',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 6. GPU类型表
-- ============================================
CREATE TABLE IF NOT EXISTS gpu_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE COMMENT 'GPU代码，如K80, V100, A100, RTX4090',
    name VARCHAR(64) NOT NULL COMMENT 'GPU名称',
    memory_mb INT COMMENT '显存MB',
    compute_capability VARCHAR(16) NULL COMMENT '计算能力',
    remark TEXT NULL COMMENT '备注',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认GPU类型
INSERT IGNORE INTO gpu_types (code, name, memory_mb) VALUES
('V100', 'NVIDIA Tesla V100', 16384),
('A100', 'NVIDIA A100', 40960),
('RTX4090', 'NVIDIA RTX 4090', 24576),
('K80', 'NVIDIA Tesla K80', 12288),
('TEST', 'Test GPU', 4096);

-- ============================================
-- 7. 节点表（物理主机）
-- ============================================
CREATE TABLE IF NOT EXISTS nodes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    hostname VARCHAR(128) NOT NULL UNIQUE COMMENT '主机名',
    ip VARCHAR(64) NOT NULL COMMENT 'IP地址',
    cpu_cores INT DEFAULT 0 COMMENT 'CPU核心数',
    memory_gb FLOAT DEFAULT 0.0 COMMENT '内存GB',
    labels JSON DEFAULT NULL COMMENT '标签（JSON格式）',
    status ENUM('online','offline','draining','maintenance') DEFAULT 'online' COMMENT '状态',
    gpus_total INT DEFAULT 0 COMMENT '总GPU数',
    gpus_free INT DEFAULT 0 COMMENT '空闲GPU数',
    cpu_usage FLOAT DEFAULT 0.0 COMMENT 'CPU使用率',
    mem_usage FLOAT DEFAULT 0.0 COMMENT '内存使用率',
    last_heartbeat DATETIME(6) NULL COMMENT '最后心跳时间',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_status (status),
    INDEX idx_hostname (hostname)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 8. GPU表（单个物理GPU单元）
-- ============================================
CREATE TABLE IF NOT EXISTS gpus (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    node_id BIGINT NOT NULL COMMENT '节点ID',
    gpu_index INT NOT NULL COMMENT 'GPU索引，如0,1...',
    gpu_type_id INT NOT NULL COMMENT 'GPU类型ID',
    uuid VARCHAR(100) NULL UNIQUE COMMENT 'GPU UUID',
    memory_gb FLOAT DEFAULT 0.0 COMMENT '显存GB',
    status ENUM('free','reserved','occupied','maintenance') DEFAULT 'free' COMMENT '状态',
    occupied_by BIGINT NULL COMMENT '被哪个用户占用',
    allocation_id BIGINT NULL COMMENT '被哪个分配占用',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (gpu_type_id) REFERENCES gpu_types(id),
    FOREIGN KEY (occupied_by) REFERENCES users(id),
    UNIQUE KEY idx_node_gpuindex (node_id, gpu_index),
    INDEX idx_status (status),
    INDEX idx_node (node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 9. 镜像表（容器镜像元数据）
-- ============================================
CREATE TABLE IF NOT EXISTS images (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL COMMENT '镜像名称',
    tag VARCHAR(100) DEFAULT 'latest' COMMENT '标签',
    repo VARCHAR(500) NULL COMMENT '仓库地址',
    description TEXT NULL COMMENT '描述',
    owner_id BIGINT NULL COMMENT '所有者ID，NULL表示公共镜像',
    visibility ENUM('public','private') DEFAULT 'public' COMMENT '可见性',
    size DECIMAL(12,2) DEFAULT 0.0 COMMENT '大小GB',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_owner (owner_id),
    INDEX idx_visibility (visibility)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 10. 配额表（用户或项目配额）
-- ============================================
CREATE TABLE IF NOT EXISTS quotas (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_type ENUM('user','project') NOT NULL COMMENT '所有者类型',
    owner_id BIGINT NOT NULL COMMENT '所有者ID',
    max_gpus INT DEFAULT 1 COMMENT '最大GPU数',
    max_instances INT DEFAULT 1 COMMENT '最大实例数',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_quota_owner (owner_type, owner_id),
    INDEX idx_owner (owner_type, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 11. 资源池表（简化版，用于快速查询）
-- ============================================
CREATE TABLE IF NOT EXISTS resource_pools (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE COMMENT '资源池名称',
    gpu_type_id INT NOT NULL COMMENT 'GPU类型ID',
    node_ids JSON NOT NULL COMMENT '节点ID列表（JSON数组）',
    total_gpus INT DEFAULT 0 COMMENT '总GPU数',
    free_gpus INT DEFAULT 0 COMMENT '空闲GPU数',
    description VARCHAR(500) NULL COMMENT '描述',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    FOREIGN KEY (gpu_type_id) REFERENCES gpu_types(id),
    INDEX idx_gpu_type (gpu_type_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 12. 分配表（用户的资源申请记录）
-- ============================================
CREATE TABLE IF NOT EXISTS allocations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL UNIQUE COMMENT '请求ID，前端或调度流水号',
    user_id BIGINT NOT NULL COMMENT '用户ID',
    project_id BIGINT NULL COMMENT '项目ID',
    pool_id INT NULL COMMENT '资源池ID',
    requested_gpu_count INT NOT NULL COMMENT '请求的GPU数量',
    gpu_type_id INT NULL COMMENT '用户优先选择的GPU类型',
    status ENUM('pending','approved','rejected','active','stopped','released','failed') DEFAULT 'pending' COMMENT '状态',
    billing_mode ENUM('on_demand','prepaid','hour','week','month') DEFAULT 'on_demand' COMMENT '计费模式',
    image_id BIGINT NULL COMMENT '镜像ID',
    image_name VARCHAR(200) NULL COMMENT '镜像名称（冗余）',
    node_id BIGINT NULL COMMENT '分配的节点ID',
    gpu_ids JSON NULL COMMENT '分配的GPU ID列表',
    container_id VARCHAR(100) NULL UNIQUE COMMENT '容器ID',
    pod_name VARCHAR(200) NULL COMMENT 'K8s Pod名称',
    ssh_port INT NULL COMMENT 'SSH端口',
    vnc_port INT NULL COMMENT 'VNC端口',
    jupyter_port INT NULL COMMENT 'Jupyter端口',
    start_time DATETIME(6) NULL COMMENT '开始时间',
    end_time DATETIME(6) NULL COMMENT '结束时间',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (gpu_type_id) REFERENCES gpu_types(id),
    FOREIGN KEY (pool_id) REFERENCES resource_pools(id),
    FOREIGN KEY (image_id) REFERENCES images(id),
    FOREIGN KEY (node_id) REFERENCES nodes(id),
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_container (container_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 13. 实例表（运行的容器/VM/作业）
-- ============================================
CREATE TABLE IF NOT EXISTS instances (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    allocation_id BIGINT NOT NULL COMMENT '分配ID',
    instance_name VARCHAR(128) NOT NULL COMMENT '实例名称，container name或VM id',
    node_id BIGINT NOT NULL COMMENT '所在节点',
    gpu_ids JSON NULL COMMENT 'GPU ID列表 [gpu_id1, gpu_id2]',
    image_id BIGINT NOT NULL COMMENT '镜像ID',
    ssh_port INT NULL COMMENT 'SSH端口',
    vnc_port INT NULL COMMENT 'VNC端口',
    jupyter_port INT NULL COMMENT 'Jupyter端口',
    status ENUM('creating','running','stopped','terminated','error') DEFAULT 'creating' COMMENT '状态',
    started_at DATETIME(6) NULL COMMENT '启动时间',
    stopped_at DATETIME(6) NULL COMMENT '停止时间',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    FOREIGN KEY (allocation_id) REFERENCES allocations(id),
    FOREIGN KEY (node_id) REFERENCES nodes(id),
    FOREIGN KEY (image_id) REFERENCES images(id),
    INDEX idx_alloc (allocation_id),
    INDEX idx_node (node_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 14. 计费费率表（管理员配置的费率）
-- ============================================
CREATE TABLE IF NOT EXISTS billing_rates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    gpu_type_id INT NOT NULL COMMENT 'GPU类型ID',
    billing_mode ENUM('hour','week','month') NOT NULL COMMENT '计费模式',
    price DECIMAL(12,4) NOT NULL DEFAULT 0.0000 COMMENT '价格，单位：货币/（小时|周|月）',
    currency VARCHAR(8) DEFAULT 'CNY' COMMENT '货币',
    effective_from DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) COMMENT '生效开始时间',
    effective_to DATETIME(6) NULL COMMENT '生效结束时间，NULL表示一直有效',
    created_by BIGINT NULL COMMENT '创建者ID',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (gpu_type_id) REFERENCES gpu_types(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_rates_type_mode (gpu_type_id, billing_mode),
    INDEX idx_effective (effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认费率（按小时）
INSERT IGNORE INTO billing_rates (gpu_type_id, billing_mode, price, currency) VALUES
((SELECT id FROM gpu_types WHERE code='V100'), 'hour', 10.0000, 'CNY'),
((SELECT id FROM gpu_types WHERE code='A100'), 'hour', 20.0000, 'CNY'),
((SELECT id FROM gpu_types WHERE code='RTX4090'), 'hour', 15.0000, 'CNY'),
((SELECT id FROM gpu_types WHERE code='K80'), 'hour', 5.0000, 'CNY');

-- ============================================
-- 15. 计费记录表（计费流水，原子级或分钟级记录）
-- ============================================
CREATE TABLE IF NOT EXISTS billing_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instance_id BIGINT NULL COMMENT '实例ID',
    allocation_id BIGINT NULL COMMENT '分配ID（冗余）',
    user_id BIGINT NOT NULL COMMENT '用户ID',
    gpu_type_id INT NOT NULL COMMENT 'GPU类型ID',
    gpu_count INT NOT NULL COMMENT 'GPU数量',
    start_time DATETIME(6) NOT NULL COMMENT '开始时间',
    end_time DATETIME(6) NOT NULL COMMENT '结束时间',
    minutes INT NOT NULL COMMENT '使用时长（分钟）',
    unit_price DECIMAL(12,4) NOT NULL COMMENT '单位价格，结算时从billing_rates复制',
    amount DECIMAL(14,4) NOT NULL COMMENT '金额 = unit_price * factor',
    billing_mode ENUM('hour','week','month') NOT NULL COMMENT '计费模式',
    settled BOOLEAN DEFAULT FALSE COMMENT '是否已结算',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL,
    FOREIGN KEY (allocation_id) REFERENCES allocations(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (gpu_type_id) REFERENCES gpu_types(id),
    INDEX idx_user_time (user_id, created_at),
    INDEX idx_instance (instance_id),
    INDEX idx_settled (settled),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 16. 发票表（发票/结算单）
-- ============================================
CREATE TABLE IF NOT EXISTS invoices (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '用户ID',
    invoice_no VARCHAR(64) NOT NULL UNIQUE COMMENT '发票号',
    period_start DATETIME(6) NOT NULL COMMENT '周期开始',
    period_end DATETIME(6) NOT NULL COMMENT '周期结束',
    total_amount DECIMAL(14,4) NOT NULL COMMENT '总金额',
    status ENUM('pending','paid','cancelled') DEFAULT 'pending' COMMENT '状态',
    issued_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) COMMENT '开具时间',
    paid_at DATETIME(6) NULL COMMENT '支付时间',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_invoice_no (invoice_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 17. 发票明细表（把billing_records聚合进发票明细）
-- ============================================
CREATE TABLE IF NOT EXISTS invoice_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NOT NULL COMMENT '发票ID',
    billing_record_id BIGINT NOT NULL COMMENT '计费记录ID',
    amount DECIMAL(14,4) NOT NULL COMMENT '金额',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (billing_record_id) REFERENCES billing_records(id) ON DELETE CASCADE,
    INDEX idx_invoice (invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 18. 支付表（充值/支付流水）
-- ============================================
CREATE TABLE IF NOT EXISTS payments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '用户ID',
    invoice_id BIGINT NULL COMMENT '发票ID',
    amount DECIMAL(14,4) NOT NULL COMMENT '金额',
    method ENUM('balance','alipay','wechat','bank','other') DEFAULT 'balance' COMMENT '支付方式',
    status ENUM('initiated','success','failed') DEFAULT 'initiated' COMMENT '状态',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    paid_at DATETIME(6) NULL COMMENT '支付时间',
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    INDEX idx_user (user_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 19. 审计日志表（操作审计）
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NULL COMMENT '用户ID',
    action VARCHAR(128) NOT NULL COMMENT '操作类型',
    resource_type VARCHAR(64) NULL COMMENT '资源类型',
    resource_id VARCHAR(64) NULL COMMENT '资源ID',
    detail JSON NULL COMMENT '详细信息（JSON格式）',
    ip_address VARCHAR(64) NULL COMMENT 'IP地址',
    user_agent VARCHAR(500) NULL COMMENT 'User Agent',
    result VARCHAR(50) DEFAULT 'success' COMMENT '结果（success/failed）',
    timestamp DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id),
    INDEX idx_action (action),
    INDEX idx_time (timestamp),
    INDEX idx_resource (resource_type, resource_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 20. 设置表（关键平台设置）
-- ============================================
CREATE TABLE IF NOT EXISTS settings (
    k VARCHAR(128) PRIMARY KEY COMMENT '配置键',
    v TEXT COMMENT '配置值',
    description VARCHAR(500) NULL COMMENT '描述',
    updated_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认设置
INSERT IGNORE INTO settings (k, v, description) VALUES
('platform_name', '算力云平台', '平台名称'),
('maintenance_mode', 'false', '维护模式'),
('max_gpu_per_user', '10', '每用户最大GPU数'),
('default_quota_gpus', '1', '默认配额GPU数');

-- ============================================
-- 21. 备份表（快照/镜像备份记录）
-- ============================================
CREATE TABLE IF NOT EXISTS backups (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instance_id BIGINT NULL COMMENT '实例ID',
    backup_path VARCHAR(512) COMMENT '备份路径',
    backup_size BIGINT COMMENT '备份大小（字节）',
    backup_type ENUM('snapshot','image','data') DEFAULT 'snapshot' COMMENT '备份类型',
    created_by BIGINT NULL COMMENT '创建者ID',
    created_at DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by) REFERENCES users(id),
    INDEX idx_instance (instance_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- 完成
-- ============================================
SELECT 'Database schema created successfully!' AS message;

