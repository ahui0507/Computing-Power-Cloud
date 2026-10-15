"""
用户详情模型
"""
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class UserProfile(Base):
    """用户详情表"""
    __tablename__ = "user_profiles"
    
    user_id = Column(BigInteger, ForeignKey("users.id"), primary_key=True, comment="用户ID")
    full_name = Column(String(128), nullable=True, comment="全名")
    organization = Column(String(128), nullable=True, comment="组织")
    avatar_url = Column(String(255), nullable=True, comment="头像URL")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    
    # 关系
    user = relationship("User", back_populates="profile")
    
    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id}, full_name={self.full_name})>"

