"""
应用配置
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
from typing import List, Optional
import json
import os
from pathlib import Path


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "Computing Power Cloud Platform"
    APP_VERSION: str = "0.9.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = Field(default=8000, ge=1, le=65535)

    # 数据库配置
    DATABASE_URL: str = "mysql+pymysql://REPLACE_DB_USER:REPLACE_DB_PASSWORD@localhost:3306/computing_platform"
    DATABASE_ECHO: bool = False

    # Redis配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_USERNAME: Optional[str] = None
    REDIS_PASSWORD: Optional[str] = None

    # JWT配置
    SECRET_KEY: str = ""
    INITIAL_ACCOUNT_PASSWORD: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_MAX_FAILURES: int = Field(default=10, ge=3, le=100)
    LOGIN_WINDOW_SECONDS: int = Field(default=900, ge=60, le=3600)
    RESOURCE_QUEUE_TTL_HOURS: int = Field(default=24, ge=1, le=168)
    ADMIN_ALERTS_ENABLED: bool = True
    GPU_TEMPERATURE_ALERT_C: float = Field(default=85, ge=60, le=110)
    BACKUP_MAX_AGE_HOURS: int = Field(default=48, ge=1)
    BACKUP_ALERTS_ENABLED: bool = True
    WORKLOAD_EPHEMERAL_GIB_PER_GPU: int = Field(default=40, ge=1, le=200)
    RECONCILIATION_HEARTBEAT_FILE: str = ""
    INSTANCE_SAFETY_ENABLED: bool = False

    # 短信服务配置
    SMS_PROVIDER: str = "local"  # aliyun, tencent, local
    SMS_ACCESS_KEY_ID: Optional[str] = None
    SMS_ACCESS_KEY_SECRET: Optional[str] = None
    SMS_SIGN_NAME: Optional[str] = None
    SMS_TEMPLATE_CODE: Optional[str] = None

    # 邮件服务配置
    SMTP_HOST: str = "smtp.exmail.qq.com"
    SMTP_PORT: int = 465
    SMTP_USE_SSL: bool = True
    SMTP_USERNAME: str = "REPLACE_SMTP_EMAIL"
    SMTP_PASSWORD: Optional[str] = None  # 需要在环境变量中配置
    SMTP_FROM_EMAIL: str = "REPLACE_SMTP_EMAIL"

    # MinIO/S3配置
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "REPLACE_MINIO_ACCESS_KEY"
    MINIO_SECRET_KEY: str = "REPLACE_MINIO_SECRET_KEY"
    MINIO_BUCKET: str = "computing-platform"
    MINIO_SECURE: bool = False

    # Kubernetes配置
    K8S_CONFIG_PATH: Optional[str] = None
    K8S_API_SERVER: Optional[str] = None
    K8S_NAMESPACE: str = "default"
    K8S_REQUEST_TIMEOUT_SECONDS: int = Field(default=10, gt=0)
    K8S_DELETE_TIMEOUT_SECONDS: int = Field(default=30, gt=0)
    K8S_IMAGE_PULL_POLICY: str = "Never"
    K8S_GPU_RUNTIME_CLASS: str = "nvidia"
    WORKLOAD_SHM_SIZE_LIMIT: str = Field(default="1Gi", pattern=r"^[1-9]\d*(?:Mi|Gi)$")
    WORKLOAD_NCCL_P2P_DISABLE: bool = False
    WORKLOAD_ISOLATION_ENABLED: bool = False
    WORKLOAD_NETWORK_POLICY_SHA256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    NODE_RESERVED_CPU_PERCENT: float = Field(default=20, ge=0, lt=100)
    NODE_RESERVED_RAM_PERCENT: float = Field(default=20, ge=0, lt=100)
    JUPYTER_COMMAND: str = "jupyter-lab"
    SSH_ENABLED: bool = False
    WORKER_AGENT_URLS: str = "{}"
    WORKER_AGENT_TOKEN: str = ""
    IMAGE_STORE_ROOT: str = "/srv/platform-images"
    IMAGE_SAVE_TIMEOUT_SECONDS: int = Field(default=1800, ge=60)
    WORKSPACE_PVC_NAME: str = "platform-workspaces"
    WORKSPACE_GID: int = 1000
    STORAGE_ROOT: str = str(Path(__file__).resolve().parents[2] / "storage")
    MAX_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    STORAGE_QUOTA_ENABLED: bool = False
    STORAGE_QUOTA_MODE: str = Field(default="fixed", pattern="^(fixed|percent)$")
    DEFAULT_STORAGE_LIMIT_GIB: int = Field(default=300, ge=1)
    STORAGE_QUOTA_HELPER: str = "/usr/local/sbin/platform-storage"
    DEFAULT_STORAGE_SHARE_PERCENT: float = Field(default=10, gt=0, le=100)
    STORAGE_WARNING_PERCENT: float = Field(default=80, gt=0, le=100)
    BACKUP_STATUS_FILE: str = "/var/lib/images/platform-data/backup-status.json"
    NOTICE_RETENTION_DAYS: int = Field(default=90, ge=7, le=365)
    INITIAL_ADMIN_EMAIL: str = "REPLACE_ADMIN_EMAIL"
    INITIAL_ADMIN_USERNAME: str = ""
    AUTO_INIT_DATABASE: bool = True
    DATABASE_STARTUP_TIMEOUT_SECONDS: int = Field(default=60, gt=0)
    RECONCILIATION_ENABLED: bool = True
    RECONCILIATION_INTERVAL_SECONDS: int = Field(default=15, ge=1)
    RECONCILIATION_BATCH_SIZE: int = Field(default=50, ge=1, le=500)
    OPERATION_LEASE_SECONDS: int = Field(default=300, ge=60)
    OPERATION_RETRY_SECONDS: int = Field(default=10, ge=1)
    WORKLOAD_STARTUP_TIMEOUT_SECONDS: int = Field(default=900, ge=60)

    # Ingress配置（服务暴露方案）
    INGRESS_ENABLED: bool = True  # 是否启用 Ingress（生产环境必须为 True）
    INGRESS_HOST: str = "platform.local"  # Ingress 域名（需要与实际访问域名一致）
    INGRESS_CLASS: str = "traefik"  # Ingress Controller 类型（k3s 默认使用 traefik）
    INGRESS_USE_TLS: bool = False  # 是否启用 TLS（内网测试可设为 False）
    # Public reverse proxy terminates TLS; Kubernetes Ingress may remain HTTP.
    PUBLIC_HTTPS_ENABLED: bool = False
    # Jupyter 连接网址使用控制节点：若设置 CONTROL_NODE_ID，则 Jupyter URL 的 host 取该节点的 ip，否则用 INGRESS_HOST
    CONTROL_NODE_ID: Optional[int] = None  # 控制节点在 nodes 表中的 id，用于 Jupyter 访问地址

    # Harbor配置
    HARBOR_URL: Optional[str] = None
    HARBOR_USERNAME: Optional[str] = None
    HARBOR_PASSWORD: Optional[str] = None
    HARBOR_PROJECT: str = "computing-platform"

    # CORS配置（使用字符串类型，在验证器中转换为列表）
    # 格式：多个来源用逗号分隔，如 "http://localhost:3000,http://your-ip:3000,https://your-domain.com"
    # 允许外部访问时，需要添加前端访问地址，例如：
    # - 开发环境: "http://localhost:3000,http://your-server-ip:3000"
    # - 生产环境: "https://your-domain.com,https://www.your-domain.com"
    # - 允许所有来源（仅测试，不推荐生产环境）: "*"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080"

    # 计费配置
    BILLING_ENABLED: bool = True
    DEFAULT_MAX_USER_GPUS: int = Field(default=8, ge=0)
    SSH_TUNNEL_ENABLED: bool = False
    SSH_JUMP_HOST: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[0-9]{1,5}$")
    SSH_GATEWAY_ENABLED: bool = False
    SSH_GATEWAY_ENDPOINT: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*:[0-9]{1,5}$")
    SSH_GATEWAY_HELPER: str = "/usr/local/sbin/platform-ssh-gateway"
    DEFAULT_MAX_USER_INSTANCES: int = Field(default=4, ge=0)
    DEFAULT_LOW_BALANCE_AMOUNT: float = Field(default=10, ge=0, allow_inf_nan=False)
    DEFAULT_LOW_BALANCE_MINUTES: int = Field(default=0, ge=0)
    DEBT_GRACE_HOURS: int = Field(default=6, ge=1)
    MINIMUM_BALANCE_MINUTES: int = Field(default=1, ge=0)
    TELEMETRY_STALE_SECONDS: int = Field(default=60, ge=15)
    TELEMETRY_RETENTION_DAYS: int = Field(default=7, ge=1, le=90)
    TELEMETRY_ENFORCE_FRESHNESS: bool = False
    TELEMETRY_CLEANUP_ENABLED: bool = True
    DEFAULT_GPU_PRICE_V100: float = 10.0
    DEFAULT_GPU_PRICE_A100: float = 5.0
    DEFAULT_GPU_PRICE_RTX4090: float = 15.0
    DEFAULT_GPU_PRICE_K80: float = 5.0

    @model_validator(mode="before")
    @classmethod
    def use_defaults_for_empty_values(cls, values):
        # 当前固定的 pydantic-settings 版本未提供 env_ignore_empty。
        if isinstance(values, dict):
            return {key: value for key, value in values.items() if value != ""}
        return values

    @model_validator(mode="after")
    def validate_operation_lease(self):
        # 创建/删除最多含十次有界 RPC，删除轮询额外计入自身截止时间。
        minimum = 10 * self.K8S_REQUEST_TIMEOUT_SECONDS + self.K8S_DELETE_TIMEOUT_SECONDS
        if self.OPERATION_LEASE_SECONDS <= minimum:
            raise ValueError(
                "OPERATION_LEASE_SECONDS 必须大于 "
                "10 * K8S_REQUEST_TIMEOUT_SECONDS + K8S_DELETE_TIMEOUT_SECONDS"
            )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        """将CORS_ORIGINS字符串转换为列表"""
        if not self.CORS_ORIGINS:
            return ["http://localhost:3000", "http://localhost:8080"]

        # 尝试解析为JSON
        if self.CORS_ORIGINS.strip().startswith("["):
            try:
                return json.loads(self.CORS_ORIGINS)
            except json.JSONDecodeError:
                pass

        # 否则按逗号分隔
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings(
    _env_file=os.environ.get("PLATFORM_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))
    or None
)
if not settings.SECRET_KEY or settings.SECRET_KEY.startswith(("your-secret-key", "REPLACE_")):
    raise ValueError("请提供已记录的 SECRET_KEY；不能使用空值或配置占位项")
elif len(settings.SECRET_KEY) < 32:
    raise ValueError("SECRET_KEY 至少需要 32 个字符")
