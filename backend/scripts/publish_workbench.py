"""登记已导入节点缓存的新版公共工作环境；先作为验收账号私有镜像测试，再公开。"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import SessionLocal
from app.core.exceptions import AuthorizationError, ResourceConflictError
from app.models import AuditLog, Image, ImageVisibility, User, UserStatus

NAME = "docker.io/library/campus-workbench"
TAG = "20261012"
DESCRIPTION = "推荐：全新 Linux 开发环境，无历史文件和终端记录；预装 Vim/Nano、下载压缩、进程网络工具和 GCC/CMake；Python 3.10、JupyterLab、SSH/SFTP、NumPy 1.26.4、PyTorch 1.13.1 + CUDA 11.7，已适配 K80。"


def register(db, admin_id, size_bytes, staging_owner_id=None, apply=False):
    actor = db.get(User, admin_id)
    if not actor or actor.deleted_at or actor.status != UserStatus.ACTIVE or actor.role != "admin":
        raise AuthorizationError("需要有效管理员操作人")
    if size_bytes <= 0:
        raise ValueError("镜像大小必须大于零")
    if staging_owner_id:
        owner = db.get(User, staging_owner_id)
        if not owner or owner.deleted_at or owner.status != UserStatus.ACTIVE:
            raise AuthorizationError("验收账号不存在或不可用")
    image = db.query(Image).filter_by(name=NAME, tag=TAG, snapshot_id=None).with_for_update().first()
    if image and image.visibility == ImageVisibility.PUBLIC and staging_owner_id:
        raise ResourceConflictError("已公开的版本不能重新改成验收私有镜像")
    visibility = ImageVisibility.PRIVATE if staging_owner_id else ImageVisibility.PUBLIC
    description = DESCRIPTION if not staging_owner_id else "待验收：" + DESCRIPTION.removeprefix("推荐：")
    values = dict(visibility=visibility, owner_id=staging_owner_id, supports_ssh=True,
                  startup_command="/opt/campus-python/bin/jupyter-lab", snapshot_status="ready", snapshot_error=None,
                  size=Decimal(str(size_bytes / 1024**3)).quantize(Decimal("0.01")), desc=description)
    changed = image is None or any(getattr(image, key) != value for key, value in values.items())
    if apply and changed:
        if image is None:
            image = Image(name=NAME, tag=TAG)
            db.add(image)
        for key, value in values.items():
            setattr(image, key, value)
        db.flush()
        db.add(AuditLog(user_id=admin_id, action="登记验收工作环境" if staging_owner_id else "发布标准开发镜像",
                        resource_type="image", resource_id=str(image.id), result="success",
                        detail={"ref": NAME + ":" + TAG, "visibility": visibility.value}))
        db.commit()
    return {"applied": apply, "changed": changed, "image_id": image.id if image else None,
            "ref": NAME + ":" + TAG, "visibility": visibility.value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-id", required=True, type=int)
    parser.add_argument("--size-bytes", required=True, type=int)
    parser.add_argument("--staging-owner-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = register(db, args.admin_id, args.size_bytes, args.staging_owner_id, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
