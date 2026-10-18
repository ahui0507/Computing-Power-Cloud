"""账户设置、镜像目录、真实审计与资源池管理。"""

import base64
import hashlib
import re
from datetime import datetime, time
from datetime import timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_admin_user
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.core.response import success_response
from app.core.security import get_password_hash, verify_password
from app.core.time import utc_iso
from app.models import (
    Allocation,
    AllocationStatus,
    Image,
    ImageVisibility,
    ResourcePool,
    User,
    Node,
)
from app.models.audit import AuditLog
from app.models.ssh_key import SSHKey
from app.core.audit import audit

router = APIRouter(tags=["控制台"])


@router.get("/platform/capabilities")
def capabilities():
    return success_response(
        data={
            "email_registration": False,
            "account_creation": "admin_only",
            "image_snapshot": bool(settings.WORKER_AGENT_TOKEN),
            "ssh_access": settings.SSH_ENABLED,
            "jobs": True,
            "workspace_path": "/workspace",
            "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
            "recharge_mode": "admin_only",
        }
    )


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value):
        if (
            len(value.encode()) > 72
            or not re.search(r"[A-Za-z]", value)
            or not re.search(r"\d", value)
        ):
            raise ValueError("新密码需包含字母和数字，且不超过72字节")
        return value


@router.post("/account/password")
def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise ResourceConflictError("当前密码不正确")
    if body.old_password == body.new_password:
        raise ResourceConflictError("新密码不能与当前密码相同")
    user.password_hash = get_password_hash(body.new_password)
    # Atomic increment also prevents concurrent password changes from reviving old sessions.
    db.query(User).filter_by(id=user.id).update({User.auth_version: User.auth_version + 1}, synchronize_session=False)
    audit(db, user, "修改密码", "user", user.id)
    db.commit()
    return success_response(message="密码已修改，所有平台登录会话已失效，请重新登录")


@router.post("/account/revoke-sessions")
def revoke_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter_by(id=user.id).update({User.auth_version: User.auth_version + 1}, synchronize_session=False)
    audit(db, user, "撤销全部登录会话", "user", user.id)
    db.commit()
    return success_response(message="所有平台登录会话已失效，请重新登录")


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    public_key: str = Field(min_length=20, max_length=16384)


@router.get("/account/keys")
def keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(
        data=[
            {
                "id": key.id,
                "name": key.name,
                "fingerprint": key.fingerprint,
                "created_at": utc_iso(key.created_at),
            }
            for key in db.query(SSHKey).filter_by(user_id=user.id).order_by(SSHKey.id.desc())
        ]
    )


@router.post("/account/keys")
def add_key(
    body: KeyInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    from cryptography.exceptions import UnsupportedAlgorithm

    value = body.public_key.strip()
    try:
        load_ssh_public_key(value.encode())
        blob = base64.b64decode(value.split()[1], validate=True)
    except (ValueError, TypeError, IndexError, UnsupportedAlgorithm) as exc:
        raise ResourceConflictError("请输入有效的 OpenSSH 公钥，请勿上传私钥") from exc
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    if db.query(SSHKey).filter_by(user_id=user.id, fingerprint=fingerprint).first():
        raise ResourceConflictError("该公钥已经保存")
    key = SSHKey(
        user_id=user.id,
        name=body.name.strip(),
        public_key=value,
        fingerprint=fingerprint,
    )
    db.add(key)
    db.flush()
    audit(db, user, "保存公钥", "ssh_key", key.id)
    db.commit()
    return success_response(data={"id": key.id})


class IdInput(BaseModel):
    id: int = Field(gt=0)


@router.post("/account/keys/delete")
def delete_key(
    body: IdInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    key = db.query(SSHKey).filter_by(id=body.id, user_id=user.id).first()
    if not key:
        raise ResourceNotFoundError("公钥")
    db.delete(key)
    audit(db, user, "删除公钥", "ssh_key", body.id)
    db.commit()
    return success_response()


class ImageInput(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    tag: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
    desc: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def image_repository(cls, value):
        if ":" in value.rsplit("/", 1)[-1]:
            raise ValueError("镜像名称不应包含版本标签，请在标签字段填写版本")
        return value


def normalized_image(value):
    first = value.split("/")[0]
    if "/" not in value:
        return "docker.io/library/" + value
    if "." not in first and ":" not in first and first != "localhost":
        return "docker.io/" + value
    return value


@router.get("/images/availability")
def image_availability(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.infrastructure.kubernetes.client import create_clients

    images = (
        db.query(Image)
        .filter((Image.visibility == ImageVisibility.PUBLIC) | (Image.owner_id == user.id))
        .all()
    )
    pools = db.query(ResourcePool).all()
    if settings.K8S_IMAGE_PULL_POLICY != "Never":
        return success_response(
            data={
                pool.id: [image.id for image in images if image.snapshot_status == "ready"]
                for pool in pools
            }
        )
    core, network = create_clients()
    try:
        nodes = core.list_node(_request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS).items
        cached = {
            node.metadata.name: {
                normalized_image(name)
                for image in (node.status.images or [])
                for name in (image.names or [])
                if name
            }
            for node in nodes
        }
    finally:
        core.api_client.close()
        if network.api_client is not core.api_client:
            network.api_client.close()
    names = {node.id: node.hostname for node in db.query(Node).all()}
    return success_response(
        data={
            pool.id: [
                image.id
                for image in images
                if image.snapshot_status == "ready"
                and any(
                    (image.snapshot_id and image.source_node_id == node_id)
                    or normalized_image(f"{image.name}:{image.tag}")
                    in cached.get(names.get(node_id), set())
                    for node_id in pool.node_ids
                )
            ]
            for pool in pools
        }
    )


@router.post("/images/register")
def register_image(
    body: ImageInput,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(Image).filter_by(owner_id=user.id, name=body.name, tag=body.tag).first():
        raise ResourceConflictError("此镜像地址已在你的目录中")
    image = Image(
        name=body.name,
        tag=body.tag,
        desc=body.desc,
        visibility=ImageVisibility.PRIVATE,
        owner_id=user.id,
    )
    db.add(image)
    db.flush()
    audit(db, user, "添加镜像地址", "image", image.id)
    db.commit()
    return success_response(data={"image_id": image.id})


@router.post("/images/delete")
def delete_image(
    body: IdInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    from app.services.quota_service import QuotaService

    QuotaService.lock_user(db, user.id)
    image = (
        db.query(Image)
        .filter_by(id=body.id, owner_id=user.id, visibility=ImageVisibility.PRIVATE)
        .first()
    )
    if not image:
        raise ResourceNotFoundError("私有镜像")
    if image.snapshot_status == "saving":
        raise ResourceConflictError("镜像正在保存，请等待完成后再删除")
    active = (
        AllocationStatus.PENDING,
        AllocationStatus.APPROVED,
        AllocationStatus.ACTIVE,
        AllocationStatus.RELEASING,
    )
    if (
        db.query(Allocation)
        .filter(Allocation.image_id == image.id, Allocation.status.in_(active))
        .first()
    ):
        raise ResourceConflictError("该镜像仍有未结束的实例，请先释放实例")
    if image.snapshot_id:
        image.snapshot_status = "deleting"
        db.commit()
        return success_response(message="个人镜像删除已提交，将清理归档和缓存")
    db.query(Allocation).filter_by(image_id=image.id).update(
        {"image_id": None}, synchronize_session=False
    )
    from app.models import Instance

    db.query(Instance).filter_by(image_id=image.id).update(
        {"image_id": None}, synchronize_session=False
    )
    db.delete(image)
    audit(db, user, "移除镜像地址", "image", body.id)
    db.commit()
    return success_response()


@router.post("/admin/delete_pool")
def delete_pool(
    body: IdInput,
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    pool = db.query(ResourcePool).filter_by(id=body.id).with_for_update().first()
    if not pool:
        raise ResourceNotFoundError("资源池")
    active = (
        AllocationStatus.PENDING,
        AllocationStatus.APPROVED,
        AllocationStatus.ACTIVE,
        AllocationStatus.RELEASING,
    )
    if (
        db.query(Allocation)
        .filter(Allocation.pool_id == pool.id, Allocation.status.in_(active))
        .first()
    ):
        raise ResourceConflictError("资源池仍有未结束实例，暂不能删除")
    db.query(Allocation).filter_by(pool_id=pool.id).update(
        {"pool_id": None}, synchronize_session=False
    )
    db.delete(pool)
    audit(db, user, "删除资源池", "pool", body.id)
    db.commit()
    return success_response()


@router.get("/admin/audit")
def audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start: str = "",
    end: str = "",
    action: str = "",
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    try:
        if start:
            date = (
                datetime.combine(
                    datetime.fromisoformat(start).date(),
                    time.min,
                    ZoneInfo("Asia/Shanghai"),
                )
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            query = query.filter(AuditLog.timestamp >= date)
        if end:
            date = (
                datetime.combine(
                    datetime.fromisoformat(end).date(),
                    time.max,
                    ZoneInfo("Asia/Shanghai"),
                )
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            query = query.filter(AuditLog.timestamp <= date)
    except ValueError as exc:
        raise ResourceConflictError("日期格式应为 YYYY-MM-DD") from exc
    if action:
        query = query.filter(AuditLog.action.contains(action, autoescape=True))
    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return success_response(
        data={
            "total": total,
            "items": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "action": row.action,
                    "resource": f"{row.resource_type or ''}/{row.resource_id or ''}",
                    "ip": row.ip_address or "",
                    "timestamp": utc_iso(row.timestamp),
                    "result": row.result,
                }
                for row in rows
            ],
        }
    )
