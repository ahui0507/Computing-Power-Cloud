"""One filesystem quota covers personal files and saved image archives."""

import json
import subprocess
import errno
from contextlib import contextmanager

from app.core.config import settings
from app.core.exceptions import ComputingPlatformException, ResourceConflictError
from app.models import Quota, OwnerType, User


class StorageQuotaService:
    @staticmethod
    def share(db, user_id):
        quota = (
            db.query(Quota).filter_by(owner_type=OwnerType.USER, owner_id=user_id).first()
            if db is not None
            else None
        )
        return (
            quota.storage_share_percent
            if quota and quota.storage_share_percent is not None
            else settings.DEFAULT_STORAGE_SHARE_PERCENT
        )

    @staticmethod
    def helper(action, user_id=None, share=None, limit_bytes=None):
        command = ["sudo", "-n", settings.STORAGE_QUOTA_HELPER, action]
        if user_id is not None:
            command.append(str(int(user_id)))
        if share is not None:
            command.extend(["--share-percent", str(share)])
        if limit_bytes is not None:
            command.extend(["--limit-bytes", str(int(limit_bytes))])
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if result.returncode == 3:
                raise ResourceConflictError("存储池可分配容量不足，或调整后的额度小于已有数据；原有文件和额度保留")
            result.check_returncode()
            return json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ComputingPlatformException(
                status_code=503, detail="存储配额服务暂不可用，请稍后重试"
            ) from error

    @staticmethod
    def prepare(db, user_id):
        share = StorageQuotaService.share(db, user_id)
        limit_bytes = None
        if settings.STORAGE_QUOTA_MODE == "fixed":
            user = db.get(User, user_id) if db is not None else None
            quota = db.query(Quota).filter_by(owner_type=OwnerType.USER, owner_id=user_id).first() if db is not None else None
            if user is not None and user.storage_default_bytes is None:
                user.storage_default_bytes = settings.DEFAULT_STORAGE_LIMIT_GIB * 1024**3
            limit_bytes = (quota.storage_limit_bytes if quota and quota.storage_limit_bytes is not None
                           else (user.storage_default_bytes if user else None)
                           or settings.DEFAULT_STORAGE_LIMIT_GIB * 1024**3)
        if not settings.STORAGE_QUOTA_ENABLED:
            return {
                "quota_mode": settings.STORAGE_QUOTA_MODE,
                "enforcement": "disabled",
                "used_percent": None,
                "share_percent": share,
                "warning": "none",
                "used_bytes": None,
                "limit_bytes": None,
            }
        result = (StorageQuotaService.helper("ensure", user_id, limit_bytes=limit_bytes)
                  if limit_bytes is not None else StorageQuotaService.helper("ensure", user_id, share))
        result["share_percent"] = share
        result["quota_mode"] = settings.STORAGE_QUOTA_MODE
        used = result["used_percent"] or 0
        result["warning"] = (
            "full" if used >= 100 else "low" if used >= settings.STORAGE_WARNING_PERCENT else "none"
        )
        return result

    @staticmethod
    def writable(db, user_id, size=1):
        result = StorageQuotaService.prepare(db, user_id)
        if result["enforcement"] == "filesystem":
            available = min(
                max(0, result["limit_bytes"] - result["used_bytes"]),
                result["volume"]["available_bytes"],
            )
            if size > available:
                raise ResourceConflictError(
                    "个人存储额度或数据卷空间不足，请清理文件、镜像或联系管理员调整额度"
                )
            if result["inode_limit"] and result["used_inodes"] >= result["inode_limit"]:
                raise ResourceConflictError(
                    "个人文件数量已达到上限，请清理文件或联系管理员调整额度"
                )
        return result

    @staticmethod
    @contextmanager
    def write_guard():
        try:
            yield
        except OSError as error:
            if error.errno in (errno.EDQUOT, errno.ENOSPC):
                raise ResourceConflictError(
                    "存储额度或空间不足，原有文件继续保留，请清理后重试"
                ) from error
            raise
