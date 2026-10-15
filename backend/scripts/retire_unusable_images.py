"""下架已核对的不可用公共镜像，保留历史关联和用户个人镜像。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.exceptions import AuthorizationError
from app.models import AuditLog, Image, ImageVisibility, User, UserStatus
from app.routers.console import normalized_image


TARGETS = {
    "docker.io/pytorch/pytorch:latest": "计算节点没有对应缓存，当前不能作为平台环境申请",
    "docker.io/nvidia/cuda:11.8.0-base-ubuntu22.04": "计算节点没有对应缓存，基础镜像也未配置完整工作环境",
    "docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518": "内置 PyTorch 2.3.0 / CUDA 12.1 不适配当前 K80，启动入口尚需适配",
    "docker.io/library/myimage:latest": "旧 NGC PyTorch 环境尚未通过当前 K80、Jupyter 接入和 SSH 验收",
    "nvcr.io/nvidia/pytorch:21.12-py3": "旧 NGC PyTorch 环境尚未通过当前 K80、Jupyter 接入和 SSH 验收",
    "docker.io/library/campus-workbench:20261010": "基础镜像带有旧测试文件，已由干净版本 campus-workbench:20261012 替代",
    "docker.io/library/campus-workbench:20261011": "基础镜像带有旧测试文件，已由干净版本 campus-workbench:20261012 替代",
    "docker.io/library/jupyter-test:latest": "基础镜像带有旧测试文件，已由干净版本 campus-workbench:20261012 替代",
}


def retire_public_images(db, admin_id, *, apply=False):
    actor = db.get(User, admin_id)
    if actor is None or actor.deleted_at is not None or actor.status != UserStatus.ACTIVE or actor.role != "admin":
        raise AuthorizationError("需要有效的管理员操作人")
    query = db.query(Image).filter(Image.visibility == ImageVisibility.PUBLIC, Image.snapshot_id.is_(None)).order_by(Image.id)
    images = query.with_for_update().all() if apply else query.all()
    result = []
    for image in images:
        ref = normalized_image(f"{image.name}:{image.tag}")
        if ref not in TARGETS or image.snapshot_status == "retired":
            continue
        result.append({"image_id": image.id, "ref": ref, "previous_status": image.snapshot_status,
                       "reason": TARGETS[ref]})
        if apply:
            db.add(AuditLog(user_id=actor.id, action="下架公共镜像", resource_type="image", resource_id=str(image.id),
                           detail={"ref": ref, "previous_status": image.snapshot_status, "reason": TARGETS[ref]}, result="success"))
            image.snapshot_status = "retired"
            image.snapshot_error = TARGETS[ref]
    if apply:
        db.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="执行下架；省略时仅输出清单")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = retire_public_images(db, args.admin_id, apply=args.apply)
    print(json.dumps({"applied": args.apply, "images": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
