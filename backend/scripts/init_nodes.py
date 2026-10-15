#!/usr/bin/env python
"""
初始化节点和GPU脚本
创建测试节点和GPU数据
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.node import Node, GPU, NodeStatus, GPUStatus
from app.models.gpu_type import GPUType


def init_nodes():
    """初始化节点和GPU"""
    db: Session = SessionLocal()
    
    try:
        # 获取所有GPU类型
        gpu_types = db.query(GPUType).all()
        if not gpu_types:
            print("⚠ No GPU types found. Please run schema.sql first.")
            return
        
        print(f"Found {len(gpu_types)} GPU types: {[gt.code for gt in gpu_types]}")
        
        # 创建测试节点
        test_nodes = [
            {
                "hostname": "node-001",
                "ip": "REPLACE_NODE_INTERNAL_IP",
                "cpu_cores": 32,
                "memory_gb": 128.0,
                "gpus": [
                    {"type": "V100", "count": 4, "memory_gb": 32.0},
                    {"type": "RTX4090", "count": 2, "memory_gb": 24.0},
                ]
            },
            {
                "hostname": "node-002",
                "ip": "REPLACE_NODE_INTERNAL_IP",
                "cpu_cores": 64,
                "memory_gb": 256.0,
                "gpus": [
                    {"type": "A100", "count": 8, "memory_gb": 40.0},
                ]
            },
            {
                "hostname": "node-003",
                "ip": "REPLACE_NODE_INTERNAL_IP",
                "cpu_cores": 16,
                "memory_gb": 64.0,
                "gpus": [
                    {"type": "K80", "count": 2, "memory_gb": 12.0},
                    {"type": "V100", "count": 2, "memory_gb": 32.0},
                ]
            },
        ]
        
        for node_data in test_nodes:
            # 检查节点是否已存在（先删除旧节点，避免枚举转换问题）
            from sqlalchemy import text
            existing_node_id = db.execute(
                text("SELECT id FROM nodes WHERE hostname = :hostname"),
                {"hostname": node_data["hostname"]}
            ).scalar()
            
            if existing_node_id:
                # 删除旧节点及其关联的GPU（避免枚举转换问题）
                db.execute(text("DELETE FROM gpus WHERE node_id = :node_id"), {"node_id": existing_node_id})
                db.execute(text("DELETE FROM nodes WHERE id = :node_id"), {"node_id": existing_node_id})
                db.flush()
                print(f"✓ Removed existing node '{node_data['hostname']}', will recreate")
            
            # 创建新节点
            # 计算总GPU数
            total_gpus = sum(gpu["count"] for gpu in node_data["gpus"])
            
            # 创建节点
            node = Node(
                hostname=node_data["hostname"],
                ip=node_data["ip"],
                cpu_cores=node_data["cpu_cores"],
                memory_gb=node_data["memory_gb"],
                gpus_total=total_gpus,
                gpus_free=total_gpus,
                status=NodeStatus.ONLINE
            )
            db.add(node)
            db.flush()  # 获取节点ID
            print(f"✓ Created node: {node_data['hostname']} ({node_data['ip']})")
            
            # 创建该节点的GPU（总是创建，因为旧节点已删除）
            gpu_index = 0
            for gpu_spec in node_data["gpus"]:
                # 查找GPU类型
                gpu_type = next((gt for gt in gpu_types if gt.code == gpu_spec["type"]), None)
                if not gpu_type:
                    print(f"⚠ GPU type '{gpu_spec['type']}' not found, skipping")
                    continue
                
                # 创建GPU（节点是新创建的，所以直接创建）
                gpus_to_create = gpu_spec["count"]
                for i in range(gpus_to_create):
                    gpu = GPU(
                        node_id=node.id,
                        gpu_index=gpu_index,
                        gpu_type_id=gpu_type.id,
                        memory_gb=gpu_spec["memory_gb"],
                        status=GPUStatus.FREE,
                        uuid=f"{node.hostname}-gpu-{gpu_index}"
                    )
                    db.add(gpu)
                    gpu_index += 1
                
                print(f"  ✓ Created {gpus_to_create} {gpu_spec['type']} GPU(s) for node {node_data['hostname']}")
            
            # 更新节点的GPU统计
            total_gpus = db.query(GPU).filter(GPU.node_id == node.id).count()
            free_gpus = db.query(GPU).filter(
                GPU.node_id == node.id,
                GPU.status == GPUStatus.FREE
            ).count()
            
            node.gpus_total = total_gpus
            node.gpus_free = free_gpus
        
        db.commit()
        print("\n✓ Nodes and GPUs initialization completed!")
        print(f"\nSummary:")
        print(f"  - Nodes: {db.query(Node).count()}")
        print(f"  - GPUs: {db.query(GPU).count()}")
        print(f"  - Free GPUs: {db.query(GPU).filter(GPU.status == GPUStatus.FREE).count()}")
        
    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_nodes()

