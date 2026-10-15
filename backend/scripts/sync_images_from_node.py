#!/usr/bin/env python3
"""
从K3s节点同步镜像到数据库
扫描当前节点中的所有镜像，并将其添加到数据库中

使用方法:
    python scripts/sync_images_from_node.py [选项]

示例:
    python scripts/sync_images_from_node.py
    python scripts/sync_images_from_node.py --dry-run  # 仅查看，不实际添加
    python scripts/sync_images_from_node.py --filter "jupyter"  # 只同步包含jupyter的镜像
    python scripts/sync_images_from_node.py --visibility private --owner-id 1  # 添加为私有镜像
"""
import sys
import os
import subprocess
import re
import argparse
from pathlib import Path
from typing import List, Tuple, Optional

# 获取backend目录路径
backend_dir = Path(__file__).parent.parent
backend_dir = backend_dir.resolve()

sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.image import Image, ImageVisibility


def find_ctr_command() -> Optional[str]:
    """查找K3s的ctr命令"""
    try:
        result = subprocess.run(
            ["sudo", "find", "/var/lib/rancher", "-name", "ctr"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0]
    except Exception as e:
        print(f"⚠ 查找ctr命令时出错: {e}")
    return None


def get_images_from_containerd(ctr_path: str) -> List[Tuple[str, str, float]]:
    """
    从containerd获取镜像列表
    返回: [(name, tag, size_gb), ...]
    """
    images = []
    
    try:
        # 使用ctr命令列出镜像
        result = subprocess.run(
            ["sudo", ctr_path, "-n", "k8s.io", "images", "ls"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"⚠ 执行ctr命令失败: {result.stderr}")
            return images
        
        # 解析输出
        # 格式示例:
        # REF                                 TYPE    DIGEST         SIZE      PLATFORMS   LABELS
        # docker.io/library/nginx:latest     application/vnd.docker.distribution.manifest.v2+json sha256:xxx 150.5 MiB linux/amd64
        # nginx:latest                        application/vnd.docker.distribution.manifest.v2+json sha256:xxx 150.5 MiB linux/amd64
        
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            print("⚠ 未找到镜像")
            return images
        
        # 跳过标题行
        for line in lines[1:]:
            if not line.strip():
                continue
            
            # 解析行
            parts = line.split()
            if len(parts) < 2:
                continue
            
            # 获取镜像引用（第一列）
            image_ref = parts[0]
            
            # 解析镜像名称和标签
            name, tag = parse_image_ref(image_ref)
            if not name:
                continue
            
            # 尝试获取镜像大小（通常在SIZE列）
            size_gb = 0.0
            for part in parts:
                # 查找类似 "150.5 MiB" 或 "2.3 GiB" 的格式
                size_match = re.search(r'(\d+\.?\d*)\s*(MiB|GiB|MB|GB)', part, re.IGNORECASE)
                if size_match:
                    size_value = float(size_match.group(1))
                    size_unit = size_match.group(2).upper()
                    if 'GI' in size_unit or 'GB' in size_unit:
                        size_gb = size_value
                    elif 'MI' in size_unit or 'MB' in size_unit:
                        size_gb = size_value / 1024.0
                    break
            
            images.append((name, tag, size_gb))
        
        return images
    
    except subprocess.TimeoutExpired:
        print("⚠ 执行ctr命令超时")
        return images
    except Exception as e:
        print(f"⚠ 获取镜像列表时出错: {e}")
        return images


def parse_image_ref(image_ref: str) -> Tuple[str, str]:
    """
    解析镜像引用，提取名称和标签
    示例:
        docker.io/library/nginx:latest -> (nginx, latest)
        nginx:latest -> (nginx, latest)
        registry.k8s.io/pause:3.9 -> (pause, 3.9)
        myimage -> (myimage, latest)
    """
    # 移除仓库前缀
    # docker.io/library/nginx:latest -> nginx:latest
    # registry.k8s.io/pause:3.9 -> pause:3.9
    
    # 处理常见的仓库前缀
    prefixes = [
        "docker.io/library/",
        "docker.io/",
        "registry.k8s.io/",
        "k8s.gcr.io/",
        "gcr.io/",
        "quay.io/",
    ]
    
    name_tag = image_ref
    for prefix in prefixes:
        if name_tag.startswith(prefix):
            name_tag = name_tag[len(prefix):]
            break
    
    # 分离名称和标签
    if ':' in name_tag:
        name, tag = name_tag.rsplit(':', 1)
    else:
        name = name_tag
        tag = "latest"
    
    # 清理名称（移除多余的斜杠）
    name = name.strip('/')
    
    return name, tag


def get_image_size_from_inspect(ctr_path: str, image_ref: str) -> float:
    """通过inspect命令获取镜像大小（GB）"""
    try:
        result = subprocess.run(
            ["sudo", ctr_path, "-n", "k8s.io", "images", "inspect", image_ref],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # 解析JSON输出，查找size字段
            import json
            data = json.loads(result.stdout)
            if 'size' in data:
                # size通常是字节，转换为GB
                size_bytes = data['size']
                return size_bytes / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def sync_images_to_database(
    images: List[Tuple[str, str, float]],
    db: Session,
    visibility: str = "public",
    owner_id: Optional[int] = None,
    filter_pattern: Optional[str] = None,
    dry_run: bool = False
) -> dict:
    """
    将镜像同步到数据库
    返回统计信息
    """
    stats = {
        "total": len(images),
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "filtered": 0
    }
    
    print(f"\n开始同步 {len(images)} 个镜像到数据库...")
    print("=" * 60)
    
    for name, tag, size_gb in images:
        # 应用过滤
        if filter_pattern and filter_pattern.lower() not in name.lower():
            stats["filtered"] += 1
            continue
        
        # 检查是否已存在
        existing = db.query(Image).filter(
            Image.name == name,
            Image.tag == tag
        ).first()
        
        if existing:
            if not dry_run:
                # 更新大小（如果之前是0）
                if existing.size == 0.0 and size_gb > 0:
                    existing.size = size_gb
                    db.commit()
                    stats["updated"] += 1
                    print(f"✓ 更新镜像: {name}:{tag} (大小: {size_gb:.2f} GB)")
                else:
                    stats["skipped"] += 1
                    print(f"⊘ 跳过已存在: {name}:{tag}")
            else:
                stats["skipped"] += 1
                print(f"⊘ [DRY-RUN] 已存在: {name}:{tag}")
        else:
            if not dry_run:
                # 创建新镜像记录
                image = Image(
                    name=name,
                    tag=tag,
                    desc=f"从节点同步的镜像: {name}:{tag}",
                    size=size_gb,
                    visibility=ImageVisibility(visibility),
                    owner_id=owner_id
                )
                db.add(image)
                db.commit()
                db.refresh(image)
                stats["added"] += 1
                print(f"✓ 添加镜像: {name}:{tag} (大小: {size_gb:.2f} GB, ID: {image.id})")
            else:
                stats["added"] += 1
                print(f"✓ [DRY-RUN] 将添加: {name}:{tag} (大小: {size_gb:.2f} GB)")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="从K3s节点同步镜像到数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 同步所有镜像
  python scripts/sync_images_from_node.py
  
  # 仅查看，不实际添加
  python scripts/sync_images_from_node.py --dry-run
  
  # 只同步包含jupyter的镜像
  python scripts/sync_images_from_node.py --filter "jupyter"
  
  # 添加为私有镜像
  python scripts/sync_images_from_node.py --visibility private --owner-id 1
        """
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅查看，不实际添加到数据库"
    )
    
    parser.add_argument(
        "--filter", "-f",
        help="只同步包含指定字符串的镜像名称"
    )
    
    parser.add_argument(
        "--visibility", "-v",
        choices=["public", "private"],
        default="public",
        help="镜像可见性（默认: public）"
    )
    
    parser.add_argument(
        "--owner-id", "-o",
        type=int,
        help="所有者ID（私有镜像需要）"
    )
    
    args = parser.parse_args()
    
    print("=== 从K3s节点同步镜像到数据库 ===")
    print()
    
    # 查找ctr命令
    print("1. 查找ctr命令...")
    ctr_path = find_ctr_command()
    if not ctr_path:
        print("✗ 未找到K3s的ctr命令")
        print("请确保K3s已安装并在当前节点上运行")
        return 1
    
    print(f"✓ 找到ctr命令: {ctr_path}")
    print()
    
    # 获取镜像列表
    print("2. 获取节点中的镜像列表...")
    images = get_images_from_containerd(ctr_path)
    
    if not images:
        print("⚠ 未找到任何镜像")
        return 1
    
    print(f"✓ 找到 {len(images)} 个镜像")
    print()
    
    # 显示镜像列表
    print("镜像列表:")
    print("-" * 60)
    for name, tag, size_gb in images[:10]:  # 只显示前10个
        size_str = f"{size_gb:.2f} GB" if size_gb > 0 else "未知"
        print(f"  {name}:{tag} ({size_str})")
    if len(images) > 10:
        print(f"  ... 还有 {len(images) - 10} 个镜像")
    print()
    
    if args.dry_run:
        print("⚠ DRY-RUN 模式：不会实际修改数据库")
        print()
    
    # 同步到数据库
    db = SessionLocal()
    try:
        stats = sync_images_to_database(
            images=images,
            db=db,
            visibility=args.visibility,
            owner_id=args.owner_id,
            filter_pattern=args.filter,
            dry_run=args.dry_run
        )
        
        print()
        print("=" * 60)
        print("同步完成！")
        print(f"  总计: {stats['total']}")
        print(f"  添加: {stats['added']}")
        print(f"  更新: {stats['updated']}")
        print(f"  跳过: {stats['skipped']}")
        if args.filter:
            print(f"  过滤: {stats['filtered']}")
        print("=" * 60)
        
    except Exception as e:
        db.rollback()
        print(f"✗ 同步失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
