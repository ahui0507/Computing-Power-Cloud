from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.core.config import settings
from app.core.workspace import PERSISTENT_PATH, WORKSPACE_PATH, SEPARATE_LAYOUT
from app.models import User
from app.services.ssh_service import SSHService
from app.services.storage_service import StorageService

router = APIRouter(tags=["个人工作环境"])


@router.post("/resource/{container_id}/ssh")
def ssh_connection(
    container_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return success_response(data=SSHService.connection(db, user.id, container_id))


@router.get("/storage/info")
def storage_info(user: User = Depends(get_current_user)):
    root = StorageService.user_root(user.id)
    return success_response(
        data={
            "instance_path": PERSISTENT_PATH,
            "workspace_path": WORKSPACE_PATH,
            "storage_layout": SEPARATE_LAYOUT,
            "server_path": str(root),
            "shared_across_instances": True,
            "retained_after_release": True,
            "image_store_path": f"{settings.IMAGE_STORE_ROOT}/user_{user.id}",
        }
    )
