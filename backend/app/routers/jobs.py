from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.models import User
from app.core.audit import audit
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["任务"])


class JobInput(BaseModel):
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    container_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=8192)


@router.get("")
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(data=JobService.list(db, user.id))


@router.post("")
async def submit_job(
    body: JobInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await JobService.submit(db, user.id, body)
    audit(db, user, "提交任务", "job", body.job_id)
    db.commit()
    return success_response(data=result)


@router.get("/{job_id}/logs")
def logs(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    JobService.get(db, user.id, job_id)
    return success_response(
        data={
            "logs": JobService.read(user.id, JobService.relative(job_id, "output.log"), tail=True)
            or ""
        }
    )


@router.post("/{job_id}/cancel")
async def cancel(
    job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    result = await JobService.cancel(db, user.id, job_id)
    audit(db, user, "取消任务", "job", job_id)
    db.commit()
    return success_response(data=result)
