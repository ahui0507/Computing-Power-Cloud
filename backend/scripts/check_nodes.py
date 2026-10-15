#!/usr/bin/env python
"""
检查数据库中的节点
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.node import Node


def check_nodes():
    """检查数据库中的节点"""
    db: Session = SessionLocal()
    
    try:
        nodes = db.query(Node).all()
        
        print("=" * 60)
        print("数据库中的节点列表")
        print("=" * 60)
        
        if not nodes:
            print("⚠ 数据库中没有节点记录")
            print("\n提示：需要运行同步脚本将 Kubernetes 节点同步到数据库")
            print("运行: python scripts/sync_nodes_from_k8s.py")
        else:
            print(f"\n找到 {len(nodes)} 个节点：\n")
            for node in nodes:
                print(f"  ID: {node.id}")
                print(f"  主机名: {node.hostname}")
                print(f"  IP地址: {node.ip}")
                print(f"  CPU核心数: {node.cpu_cores}")
                print(f"  内存(GB): {node.memory_gb}")
                print(f"  GPU总数: {node.gpus_total}")
                print(f"  空闲GPU: {node.gpus_free}")
                print(f"  状态: {node.status.value}")
                print(f"  创建时间: {node.created_at}")
                print(f"  更新时间: {node.updated_at}")
                print("-" * 60)
        
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    check_nodes()

