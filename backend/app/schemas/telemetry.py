from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


class GPUMetricInput(BaseModel):
    compute_capability: Optional[str] = Field(default=None, max_length=16, pattern=r"^[0-9]+\.[0-9]+$")
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    index: int = Field(ge=0, le=4096)
    uuid: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=128)
    utilization: Optional[float] = Field(default=None, ge=0, le=100)
    memory_used_mb: Optional[float] = Field(default=None, ge=0, le=10000000)
    memory_total_mb: Optional[float] = Field(default=None, gt=0, le=10000000)
    temperature: Optional[float] = Field(default=None, ge=-50, le=200)
    power_watts: Optional[float] = Field(default=None, ge=0, le=10000)
    pod_uids: list[str] = Field(default_factory=list, max_length=128)


class TelemetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    node_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    collected_at: datetime
    cpu_usage: Optional[float] = Field(default=None, ge=0, le=100)
    mem_usage: Optional[float] = Field(default=None, ge=0, le=100)
    cpu_cores: int = Field(ge=1, le=4096)
    memory_total_mb: float = Field(gt=0, le=1000000000)
    memory_used_mb: float = Field(ge=0, le=1000000000)
    gpus: list[GPUMetricInput] = Field(default_factory=list, max_length=128)
    gpu_error: Optional[str] = Field(default=None, max_length=300)
    driver_version: Optional[str] = Field(default=None, max_length=64, pattern=r"^[0-9.]+$")
    driver_cuda_max: Optional[str] = Field(default=None, max_length=16, pattern=r"^[0-9.]+$")
    device_mapping_available: bool = False

    @field_validator("collected_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("采集时间必须包含时区")
        return value
