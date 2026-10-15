"""
项目模型
"""
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Project(Base):
    """项目表"""
    __tablename__ = "projects"
    
    id = Column(BigInteger, primary_key=True, index=True, comment="项目ID")
    name = Column(String(128), nullable=False, comment="项目名称")
    owner_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="所有者ID")
    description = Column(Text, nullable=True, comment="描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    
    # 关系
    owner = relationship("User", backref="projects")
    
    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name}, owner_id={self.owner_id})>"

