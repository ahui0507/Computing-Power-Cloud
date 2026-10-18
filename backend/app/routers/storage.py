"""
存储管理路由
"""

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from urllib.parse import quote
import os
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.schemas.storage import DeleteFileRequest, TrainingExampleRequest
from app.services.storage_service import StorageService
from app.models.user import User
from pydantic import BaseModel, Field
from app.core.audit import audit
from app.core.exceptions import ResourceConflictError
from app.services.storage_quota_service import StorageQuotaService

router = APIRouter(prefix="/storage", tags=["存储管理"])


@router.post("/examples/training")
def training_example(
    request: TrainingExampleRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.environment_service import EnvironmentService

    result = EnvironmentService.training_example(
        db, user.id, framework=request.framework if request else "pytorch"
    )
    audit(db, user, "创建训练示例", "folder", result["folder"])
    db.commit()
    return success_response(data=result)


@router.get("/usage")
def usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = StorageQuotaService.prepare(db, current_user.id)
    from app.services.notice_service import NoticeService

    NoticeService.storage_warning(db, current_user.id, result)
    db.commit()
    return success_response(data=result)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传文件"""
    path = await StorageService.upload_file(
        db=db, user_id=current_user.id, file=file, folder=folder
    )
    return success_response(data={"path": path})


@router.get("/list")
async def list_files(
    folder: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取文件列表"""
    files = await StorageService.list_files(db=db, user_id=current_user.id, folder=folder)
    return success_response(data=files)


@router.post("/delete")
async def delete_file(
    request: DeleteFileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除文件"""
    await StorageService.delete_file(db=db, user_id=current_user.id, path=request.path)
    return success_response(message="File deleted")


@router.get("/download", response_class=StreamingResponse)
async def download_file(path: str, current_user: User = Depends(get_current_user)):
    stream, name = StorageService.open_download(current_user.id, path)
    length = os.fstat(stream.fileno()).st_size

    def chunks():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "Content-Length": str(length),
            "Cache-Control": "private, no-store",
        },
    )


class FolderInput(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


@router.post("/folder")
def create_folder(
    body: FolderInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    StorageQuotaService.writable(db, user.id)
    with (
        StorageQuotaService.write_guard(),
        StorageService._parent(user.id, body.path) as (path, parent),
    ):
        try:
            os.mkdir(
                path.name if parent is not None else path,
                0o770,
                **({"dir_fd": parent} if parent is not None else {}),
            )
        except FileExistsError as exc:
            raise ResourceConflictError("同名文件或目录已经存在") from exc
    audit(db, user, "创建文件夹", "folder", body.path)
    db.commit()
    return success_response()
