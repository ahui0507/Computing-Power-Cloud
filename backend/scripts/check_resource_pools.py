#!/usr/bin/env python
"""
检查资源池状态脚本
用于诊断资源池相关问题
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
from sqlalchemy import func, and_


def check_resource_pools():
    """检查资源池状态"""
    db: Session = SessionLocal()
    
    try:
        print("=" * 60)
        print("资源池状态检查")
        print("=" * 60)
        
        # 1. 检查资源池数量
        pool_count = db.query(ResourcePool).count()
        print(f"\n1. 资源池数量: {pool_count}")
        
        if pool_count == 0:
            print("   ⚠ 没有找到任何资源池！")
            print("   💡 解决方案：")
            print("      - 运行脚本: python backend/scripts/init_resource_pools.py")
            print("      - 或在管理面板手动创建资源池")
            return
        
        # 2. 检查GPU类型
        gpu_types = db.query(GPUType).all()
        print(f"\n2. GPU类型数量: {len(gpu_types)}")
        for gpu_type in gpu_types:
            print(f"   - {gpu_type.code} (ID: {gpu_type.id})")
        
        # 3. 检查节点和GPU
        nodes = db.query(Node).filter(Node.status == NodeStatus.ONLINE).all()
        print(f"\n3. 在线节点数量: {len(nodes)}")
        for node in nodes:
            gpu_count = db.query(func.count(GPU.id)).filter(GPU.node_id == node.id).scalar()
            print(f"   - {node.hostname} (ID: {node.id}, GPU: {gpu_count})")
        
        # 4. 检查每个资源池的详细信息
        print(f"\n4. 资源池详细信息:")
        pools = db.query(ResourcePool).all()
        for pool in pools:
            print(f"\n   资源池: {pool.name} (ID: {pool.id})")
            print(f"   - GPU类型ID: {pool.gpu_type_id}")
            
            # 获取GPU类型
            gpu_type = db.query(GPUType).filter(GPUType.id == pool.gpu_type_id).first()
            if gpu_type:
                print(f"   - GPU类型: {gpu_type.code}")
            else:
                print(f"   - GPU类型: ⚠ 未找到 (ID: {pool.gpu_type_id})")
            
            # 检查节点ID
            node_ids = pool.node_ids if isinstance(pool.node_ids, list) else []
            print(f"   - 关联节点ID: {node_ids}")
            
            if not node_ids:
                print(f"   - ⚠ 警告: 资源池没有关联任何节点！")
            else:
                # 检查节点是否存在
                nodes_in_pool = db.query(Node).filter(Node.id.in_(node_ids)).all()
                if len(nodes_in_pool) != len(node_ids):
                    print(f"   - ⚠ 警告: 部分节点不存在！")
                    print(f"     期望: {len(node_ids)} 个节点")
                    print(f"     实际: {len(nodes_in_pool)} 个节点")
            
            # 计算实际的GPU数量
            if node_ids:
                total_gpus = db.query(func.count(GPU.id)).filter(
                    and_(
                        GPU.node_id.in_(node_ids),
                        GPU.gpu_type_id == pool.gpu_type_id
                    )
                ).scalar() or 0
                
                free_gpus = db.query(func.count(GPU.id)).filter(
                    and_(
                        GPU.node_id.in_(node_ids),
                        GPU.gpu_type_id == pool.gpu_type_id,
                        GPU.status == 'free'
                    )
                ).scalar() or 0
                
                print(f"   - 实际总GPU数: {total_gpus}")
                print(f"   - 实际空闲GPU数: {free_gpus}")
                print(f"   - 数据库记录的总GPU数: {pool.total_gpus}")
                print(f"   - 数据库记录的空闲GPU数: {pool.free_gpus}")
                
                if total_gpus == 0:
                    print(f"   - ⚠ 警告: 资源池中没有匹配的GPU！")
                    print(f"     可能原因:")
                    print(f"     1. 节点上没有该类型的GPU")
                    print(f"     2. GPU的gpu_type_id与资源池的gpu_type_id不匹配")
            else:
                print(f"   - ⚠ 警告: 无法计算GPU数量（没有关联节点）")
        
        print("\n" + "=" * 60)
        print("检查完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"✗ 检查失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    check_resource_pools()

