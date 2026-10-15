"""
计费路由
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response, ApiResponse
from app.schemas.billing import BillingRecordResponse
from app.core.exceptions import AuthorizationError
from app.services.billing_service import BillingService
from app.services.balance_credit_service import BalanceCreditService
from app.models.user import User
from app.core.time import utc_iso

router = APIRouter(prefix="/billing", tags=["计费"])


@router.get("/credits")
def balance_credits(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(data=BalanceCreditService.history(db, current_user.id, page, page_size))


@router.get("/price", response_model=ApiResponse[dict[str, float]])
async def get_price(db: Session = Depends(get_db)):
    """获取GPU单价"""
    prices = BillingService.get_prices(db)
    return success_response(data=prices)


@router.get("/records", response_model=ApiResponse[list[BillingRecordResponse]])
async def get_records(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """获取消费记录"""
    records = BillingService.get_user_records(db, current_user.id)
    return success_response(
        data=[
            {
                "id": record.id,
                "container_id": record.container_id or "",
                "instance_name": record.instance.instance_name if record.instance else None,
                "billing_mode": record.billing_mode.value,
                "charged_at": utc_iso(record.created_at),
                "amount": float(record.amount),
                "start_time": utc_iso(record.start_time),
                "end_time": utc_iso(record.end_time),
            }
            for record in records
        ]
    )


@router.post("/recharge")
async def recharge(
    current_user: User = Depends(get_current_user),
):
    raise AuthorizationError("自助充值已关闭，请联系管理员增加余额")
