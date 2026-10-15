#!/usr/bin/env python
"""
添加Test GPU类型到数据库
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.gpu_type import GPUType


def add_test_gpu_type():
    """添加Test GPU类型"""
    db: Session = SessionLocal()
    
    try:
        # 检查是否已存在
        existing = db.query(GPUType).filter(GPUType.code == 'TEST').first()
        if existing:
            print(f"✓ Test GPU类型已存在: {existing.code} - {existing.name}")
            return
        
        # 创建Test GPU类型
        test_gpu = GPUType(
            code='TEST',
            name='Test GPU',
            memory_mb=4096,
            remark='用于测试的GPU类型'
        )
        db.add(test_gpu)
        db.commit()
        db.refresh(test_gpu)
        
        print(f"✓ 成功添加Test GPU类型: {test_gpu.code} - {test_gpu.name}")
        
    except Exception as e:
        db.rollback()
        print(f"✗ 添加失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    add_test_gpu_type()

