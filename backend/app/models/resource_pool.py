"""
资源池模型
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ResourcePool(Base):
    """资源池表"""
    __tablename__ = "resource_pools"
    
    id = Column(Integer, primary_key=True, index=True, comment="资源池ID")
    name = Column(String(100), unique=True, nullable=False, comment="资源池名称")
    gpu_type_id = Column(Integer, ForeignKey("gpu_types.id"), nullable=False, comment="GPU类型ID")
    node_ids = Column(JSON, nullable=False, comment="节点ID列表（JSON数组）")
    total_gpus = Column(Integer, default=0, comment="总GPU数")
    free_gpus = Column(Integer, default=0, comment="空闲GPU数")
    description = Column(String(500), nullable=True, comment="描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关系
    gpu_type_obj = relationship("GPUType", backref="resource_pools")
    
    @property
    def gpu_type(self) -> str:
        """兼容旧代码，返回GPU类型代码"""
        return self.gpu_type_obj.code if self.gpu_type_obj else "unknown"
    
    def __repr__(self):
        return f"<ResourcePool(id={self.id}, name={self.name}, gpu_type_id={self.gpu_type_id})>"

