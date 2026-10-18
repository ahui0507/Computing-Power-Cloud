import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.core.time import utc_iso
from app.models import (
    Allocation,
    AllocationStatus,
    Image,
    ImageVisibility,
    Node,
    AuditLog,
    Instance,
)
from app.services.worker_agent_client import WorkerAgentClient
from app.services.access_service import AccessService

logger = logging.getLogger(__name__)


class ImageService:
    @staticmethod
    def serialize(image):
        return {
            "image_id": image.id,
            "name": image.name,
            "display_name": image.display_name,
            "tag": image.tag,
            "desc": image.desc or "",
            "size": float(image.size or 0),
            "supports_ssh": image.supports_ssh,
            "snapshot_status": image.snapshot_status,
            "snapshot_error": image.snapshot_error,
            "is_snapshot": image.snapshot_id is not None,
            "created_at": utc_iso(image.created_at),
        }

    @staticmethod
    def get_public_images(db):
        return (
            db.query(Image)
            .filter_by(visibility=ImageVisibility.PUBLIC, snapshot_status="ready")
            .order_by(Image.supports_ssh.desc(), Image.created_at.desc(), Image.id.desc())
            .all()
        )

    @staticmethod
    def get_user_images(db, user_id):
        return db.query(Image).filter_by(owner_id=user_id, visibility=ImageVisibility.PRIVATE).all()

    @staticmethod
    def enqueue(db, image):
        allocation = (
            db.query(Allocation)
            .filter_by(container_id=image.source_container_id, user_id=image.owner_id)
            .first()
        )
        if not allocation or allocation.status != AllocationStatus.ACTIVE:
            raise ResourceConflictError("原实例已不在运行，无法保存镜像")
        node = db.get(Node, image.source_node_id)
        namespace = AccessService.allocation_options(allocation).get(
            "namespace", settings.K8S_NAMESPACE
        )
        return WorkerAgentClient.request(
            node.hostname,
            "/snapshots",
            {
                "job_id": image.snapshot_id,
                "allocation_id": allocation.id,
                "user_id": image.owner_id,
                "pod_name": allocation.pod_name,
                "namespace": namespace,
                "image_ref": f"{image.name}:{image.tag}",
            },
        )

    @staticmethod
    async def save_image_from_container(
        db, user_id, container_id, name, tag, request_id=None, desc=""
    ):
        if not settings.WORKER_AGENT_TOKEN:
            raise ResourceConflictError("个人镜像保存服务尚未启用")
        request_id = str(request_id or uuid4())
        allocation = (
            db.query(Allocation)
            .filter_by(container_id=container_id, user_id=user_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if not allocation:
            raise ResourceNotFoundError("实例")
        existing = db.query(Image).filter_by(snapshot_id=request_id).first()
        target_name = f"platform.local/user-{user_id}/{name}-{request_id.replace('-', '')[:12]}"
        if existing:
            if (
                existing.owner_id != user_id
                or existing.source_container_id != container_id
                or existing.name != target_name
                or existing.tag != tag
                or existing.desc != desc
            ):
                raise ResourceConflictError("同一保存编号不能用于不同参数")
            return existing
        if allocation.status != AllocationStatus.ACTIVE:
            raise ResourceConflictError("只能保存运行中的实例")
        from app.services.storage_quota_service import StorageQuotaService

        StorageQuotaService.writable(db, user_id)
        if allocation.package_expires_at and allocation.package_expires_at <= datetime.utcnow():
            raise ResourceConflictError("包时已到期，不能开始新的镜像保存任务")
        if (
            db.query(Image.id)
            .filter_by(source_container_id=container_id, snapshot_status="saving")
            .first()
        ):
            raise ResourceConflictError("此实例已有镜像正在保存，请等待完成")
        source = db.get(Image, allocation.image_id) if allocation.image_id else None
        image = Image(
            name=target_name,
            tag=tag,
            desc=desc,
            owner_id=user_id,
            visibility=ImageVisibility.PRIVATE,
            snapshot_id=request_id,
            snapshot_status="saving",
            source_node_id=allocation.node_id,
            source_container_id=container_id,
            startup_command=source.startup_command if source else None,
            supports_ssh=bool(source and source.supports_ssh),
        )
        db.add(image)
        db.flush()
        db.add(
            AuditLog(
                user_id=user_id,
                action="提交个人镜像保存",
                resource_type="image",
                resource_id=str(image.id),
                result="success",
            )
        )
        db.commit()
        try:
            ImageService.enqueue(db, image)
        except Exception:
            logger.warning("个人镜像任务等待后台重试: image=%s", image.id)
        return image

    @staticmethod
    def reconcile_saves(db):
        ids = [
            row[0]
            for row in db.query(Image.id)
            .filter(Image.snapshot_status.in_(["saving", "deleting"]))
            .order_by(Image.id)
            .limit(50)
            .all()
        ]
        for image_id in ids:
            image = db.get(Image, image_id)
            try:
                node = db.get(Node, image.source_node_id)
                if image.snapshot_status == "deleting":
                    result = WorkerAgentClient.request(
                        node.hostname,
                        "/snapshots/" + image.snapshot_id,
                        method="DELETE",
                    )
                    if result is None or result.get("status") == "deleted":
                        db.query(Allocation).filter_by(image_id=image.id).update(
                            {"image_id": None}, synchronize_session=False
                        )
                        db.query(Instance).filter_by(image_id=image.id).update(
                            {"image_id": None}, synchronize_session=False
                        )
                        db.add(
                            AuditLog(
                                user_id=image.owner_id,
                                action="删除个人镜像归档",
                                resource_type="image",
                                resource_id=str(image.id),
                                result="success",
                            )
                        )
                        db.delete(image)
                    db.commit()
                    continue
                result = WorkerAgentClient.request(node.hostname, "/snapshots/" + image.snapshot_id)
                if result is None:
                    result = ImageService.enqueue(db, image)
                if result and result["status"] in ("ready", "failed"):
                    image.snapshot_status = result["status"]
                    image.snapshot_error = result.get("error")
                    if result["status"] == "ready":
                        image.size = Decimal(str(result["size_bytes"] / 1024**3)).quantize(
                            Decimal("0.01")
                        )
                    db.add(
                        AuditLog(
                            user_id=image.owner_id,
                            action="个人镜像保存完成"
                            if result["status"] == "ready"
                            else "个人镜像保存失败",
                            resource_type="image",
                            resource_id=str(image.id),
                            result="success" if result["status"] == "ready" else "failed",
                        )
                    )
                elif image.created_at and datetime.utcnow() - image.created_at > timedelta(
                    seconds=settings.IMAGE_SAVE_TIMEOUT_SECONDS
                ):
                    image.snapshot_status = "failed"
                    image.snapshot_error = "保存超过最长等待时间，请联系管理员核对后重试"
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("个人镜像后台操作失败: image=%s", image_id)
                if (
                    image.snapshot_status == "saving"
                    and image.created_at
                    and datetime.utcnow() - image.created_at
                    > timedelta(seconds=settings.IMAGE_SAVE_TIMEOUT_SECONDS)
                ):
                    image.snapshot_status = "failed"
                    image.snapshot_error = "保存服务长时间不可用，请联系管理员"
                    db.commit()
