#!/usr/bin/env python3
"""
将Conda PyTorch Jupyter MMCV镜像添加到数据库
"""
import sys
import os
from pathlib import Path

# 获取backend目录路径
backend_dir = Path(__file__).parent.parent.parent / "backend"
backend_dir = backend_dir.resolve()

# 添加backend目录到路径
sys.path.insert(0, str(backend_dir))

# 切换到backend目录，确保.env文件能被正确加载
os.chdir(backend_dir)

# 现在导入配置和数据库模块
from app.core.database import SessionLocal
from app.models.image import Image, ImageVisibility


def add_conda_pytorch_jupyter_image():
    """添加Conda PyTorch Jupyter MMCV镜像到数据库"""
    db = SessionLocal()

    try:
        # 检查镜像是否已存在
        existing = (
            db.query(Image)
            .filter(Image.name == "jinglever/conda-pytorch-jupyter", Image.tag == "mmcv-20240518")
            .first()
        )

        if existing:
            existing.startup_command = "/home/appuser/.conda/envs/py38/bin/jupyter-lab"
            db.commit()
            print(f"✓ 镜像已存在: jinglever/conda-pytorch-jupyter:mmcv-20240518 (ID: {existing.id})")
            return existing

        # 创建新镜像记录
        image = Image(
            name="jinglever/conda-pytorch-jupyter",
            tag="mmcv-20240518",
            desc="Conda PyTorch Jupyter MMCV 环境镜像 - 包含PyTorch、Jupyter和MMCV等深度学习环境",
            visibility=ImageVisibility.PUBLIC,
            startup_command="/home/appuser/.conda/envs/py38/bin/jupyter-lab",
            size=6.2,  # 镜像大小（GB）
        )

        db.add(image)
        db.commit()
        db.refresh(image)

        print(f"✓ 成功添加镜像: jinglever/conda-pytorch-jupyter:mmcv-20240518 (ID: {image.id})")
        return image

    except Exception as e:
        db.rollback()
        print(f"✗ 添加镜像失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=== 添加Conda PyTorch Jupyter MMCV镜像到数据库 ===")
    add_conda_pytorch_jupyter_image()
    print("完成！")
