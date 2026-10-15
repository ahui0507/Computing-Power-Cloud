"""资源请求与响应契约，实例状态统一面向前端表达。"""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ContainerStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    RELEASING = "releasing"
    FAILED = "failed"
    RELEASED = "released"


class ResourcePoolResponse(BaseModel):
    pool_id: int
    name: str
    gpu_type: str
    total_gpus: int
    free_gpus: int
    physical_free_gpus: int = 0
    max_gpus_per_instance: int = 0
    cpu_cores_per_gpu: Optional[float] = None
    ram_mb_per_gpu: Optional[int] = None
    node_gpu_count: Optional[int] = None
    system_cpu_percent: float = 20
    system_ram_percent: float = 20
    available_cpu_cores: float = 0
    available_ram_mb: int = 0
    memory_mb: Optional[int] = None
    compute_capability: Optional[str] = None
    driver_versions: list[str] = Field(default_factory=list)
    driver_cuda_versions: list[str] = Field(default_factory=list)
    cuda_arch_max: Optional[str] = None
    recommended_environment: Optional[str] = None
    hourly_price: float = 0
    daily_price: float = 0
    weekly_price: float = 0


class ResourceSummaryResponse(BaseModel):
    total_gpus: int
    free_gpus: int
    used_gpus: int
    unavailable_gpus: int


class ApplyResourceRequest(BaseModel):
    pool_id: int = Field(gt=0)
    gpu_count: int = Field(gt=0)
    image_id: int = Field(gt=0)
    duration: Optional[int] = Field(default=None, gt=0)
    billing_mode: Literal["on_demand", "prepaid", "day", "week"] = Field(
        default="on_demand",
        description="on_demand 按时，day 包日，week 包周；prepaid 为旧值，新请求请明确选择 day 或 week",
    )


class ContainerResponse(BaseModel):
    workspace_path: str = "/workspace"
    persistent_path: str = "/workspace"
    storage_layout: str = "legacy"
    container_id: str
    instance_name: str = ""
    user_email: Optional[str] = None
    node_id: int
    node_ip: Optional[str] = None
    gpus: int
    cpu_cores: Optional[float] = None
    node_gpu_count: Optional[int] = None
    ram_mb: Optional[int] = None
    image: str
    status: ContainerStatus
    start_time: Optional[str] = None
    created_at: Optional[str] = None
    end_time: Optional[str] = None
    hourly_price: Optional[float] = None
    billing_mode: str = "on_demand"
    package_amount: Optional[float] = None
    package_expires_at: Optional[str] = None
    package_refunded: bool = False
    settled_amount: Optional[float] = None
    pool_id: Optional[int] = None
    image_id: Optional[int] = None
    status_message: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_enabled: bool = False
    vnc_port: Optional[int] = None
    jupyter_port: Optional[int] = None
    jupyter_url: Optional[str] = None


class ApplyResourceResponse(BaseModel):
    container_id: str
    node_id: int
    status: ContainerStatus
    ssh_port: Optional[int] = None
    vnc_port: Optional[int] = None
    jupyter_port: Optional[int] = None
    jupyter_url: Optional[str] = None
    message: str


class ReleaseResourceRequest(BaseModel):
    container_id: str = Field(min_length=1)


class ReleaseResourceResponse(BaseModel):
    container_id: str
    status: ContainerStatus
