"""
GPU类型模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class GPUType(Base):
    """GPU类型表"""
    __tablename__ = "gpu_types"
    
    id = Column(Integer, primary_key=True, index=True, comment="GPU类型ID")
    code = Column(String(32), unique=True, nullable=False, comment="GPU代码，如K80, V100, A100, RTX4090")
    name = Column(String(64), nullable=False, comment="GPU名称")
    memory_mb = Column(Integer, nullable=True, comment="显存MB")
    compute_capability = Column(String(16), nullable=True, comment="计算能力")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    
    # 关系
    gpus = relationship("GPU", back_populates="gpu_type")
    billing_rates = relationship("BillingRate", back_populates="gpu_type")
    
    def __repr__(self):
        return f"<GPUType(id={self.id}, code={self.code}, name={self.name})>"

