"""
计费相关Schema
"""

from pydantic import ConfigDict, BaseModel, Field
from typing import Optional
from datetime import datetime


class BillingPriceResponse(BaseModel):
    """GPU单价响应"""

    v100: float
    a100: float
    rtx4090: float
    k80: float


class BillingRecordResponse(BaseModel):
    """计费记录响应"""

    id: int
    container_id: str
    instance_name: Optional[str] = None
    billing_mode: str = "hour"
    charged_at: Optional[datetime] = None
    amount: float
    start_time: datetime
    end_time: datetime

    model_config = ConfigDict(from_attributes=True)


class RechargeRequest(BaseModel):
    """充值请求"""

    amount: float = Field(gt=0, allow_inf_nan=False)


class RechargeResponse(BaseModel):
    """充值响应"""

    balance: float
    message: str
