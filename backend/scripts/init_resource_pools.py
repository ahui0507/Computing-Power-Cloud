#!/usr/bin/env python
"""
初始化资源池脚本
创建默认资源池（需要先有节点和GPU数据）
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.resource_pool import ResourcePool
from app.models.node import Node, GPU, NodeStatus
from app.models.gpu_type import GPUType


def init_resource_pools():
    """初始化资源池"""
    db: Session = SessionLocal()
    
    try:
        # 获取所有GPU类型
        gpu_types = db.query(GPUType).all()
        if not gpu_types:
            print("⚠ No GPU types found. Please run schema.sql first.")
            return
        
        # 获取所有在线节点（使用原始SQL查询避免枚举转换问题）
        from sqlalchemy import text
        online_node_ids = db.execute(
            text("SELECT id FROM nodes WHERE status = 'online'")
        ).fetchall()
        
        if not online_node_ids:
            print("⚠ No online nodes found. Please create nodes first.")
            print("  You can create nodes via admin panel or directly in database.")
            return
        
        online_node_ids = [row[0] for row in online_node_ids]
        print(f"Found {len(online_node_ids)} online nodes")
        print(f"Found {len(gpu_types)} GPU types")
        
        # 为每种GPU类型创建一个资源池
        for gpu_type in gpu_types:
            # 检查是否已存在该类型的资源池
            existing_pool = db.query(ResourcePool).filter(
                ResourcePool.name == f"{gpu_type.code}_Pool"
            ).first()
            
            if existing_pool:
                print(f"✓ Resource pool '{existing_pool.name}' already exists")
                continue
            
            # 找到有该类型GPU的节点
            node_ids = []
            total_gpus = 0
            
            for node_id in online_node_ids:
                # 统计该节点上该类型的GPU数量（使用原始SQL查询）
                gpu_count = db.execute(
                    text("SELECT COUNT(*) FROM gpus WHERE node_id = :node_id AND gpu_type_id = :gpu_type_id"),
                    {"node_id": node_id, "gpu_type_id": gpu_type.id}
                ).scalar()
                
                if gpu_count > 0:
                    node_ids.append(node_id)
                    total_gpus += gpu_count
            
            if not node_ids:
                print(f"⚠ No nodes with {gpu_type.code} GPUs found, skipping pool creation")
                continue
            
            # 创建资源池
            pool = ResourcePool(
                name=f"{gpu_type.code}_Pool",
                gpu_type_id=gpu_type.id,
                node_ids=node_ids,
                total_gpus=total_gpus,
                free_gpus=total_gpus,  # 初始时所有GPU都是空闲的
                description=f"{gpu_type.code} GPU资源池"
            )
            db.add(pool)
            print(f"✓ Created resource pool: {pool.name} (nodes: {len(node_ids)}, GPUs: {total_gpus})")
        
        db.commit()
        print("\n✓ Resource pools initialization completed!")
        
    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_resource_pools()

