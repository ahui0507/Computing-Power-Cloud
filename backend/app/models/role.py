"""
角色模型
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Role(Base):
    """角色表"""
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True, comment="角色ID")
    name = Column(String(32), unique=True, nullable=False, comment="角色名称")
    description = Column(String(255), nullable=True, comment="角色描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    
    # 关系
    users = relationship("User", back_populates="role_obj")
    
    def __repr__(self):
        return f"<Role(id={self.id}, name={self.name})>"

