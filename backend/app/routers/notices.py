from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ResourceNotFoundError
from app.core.response import success_response
from app.models import Notice, User
from app.services.notice_service import NoticeService

router = APIRouter(prefix="/notices", tags=["站内提醒"])


@router.get("")
def listing(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(data=NoticeService.list_for_user(db, user.id))


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notice).filter_by(user_id=user.id, read_at=None).update({"read_at": datetime.utcnow()})
    db.commit()
    return success_response()


@router.post("/{notice_id}/read")
def read(
    notice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Notice).filter_by(id=notice_id, user_id=user.id).first()
    if not row:
        raise ResourceNotFoundError("提醒")
    row.read_at = row.read_at or datetime.utcnow()
    db.commit()
    return success_response()
