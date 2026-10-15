"""
镜像管理路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.schemas.image import SaveImageRequest
from app.services.image_service import ImageService
from app.models.user import User

router = APIRouter(prefix="/images", tags=["镜像管理"])


@router.get("/public")
async def get_public_images(db: Session = Depends(get_db)):
    """获取公共镜像列表"""
    images = ImageService.get_public_images(db)
    return success_response(
        data=[
            ImageService.serialize(img)
            for img in images
        ]
    )


@router.get("/my")
async def get_my_images(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """获取我的镜像"""
    images = ImageService.get_user_images(db, current_user.id)
    return success_response(
        data=[
            ImageService.serialize(img)
            for img in images
        ]
    )


@router.post("/save")
async def save_image(
    request: SaveImageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存镜像"""
    image = await ImageService.save_image_from_container(
        db=db,
        user_id=current_user.id,
        container_id=request.container_id,
        name=request.name,
        tag=request.tag,
        request_id=request.request_id,
        desc=request.desc,
    )
    return success_response(data={"image_id": image.id, "status": image.snapshot_status}, message="镜像保存任务已提交")
