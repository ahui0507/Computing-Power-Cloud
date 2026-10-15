"""
SSH密钥模型
"""
from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class SSHKey(Base):
    """SSH密钥表"""
    __tablename__ = "ssh_keys"
    
    id = Column(BigInteger, primary_key=True, index=True, comment="密钥ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="用户ID")
    name = Column(String(128), nullable=False, comment="密钥名称")
    public_key = Column(Text, nullable=False, comment="公钥内容")
    fingerprint = Column(String(128), nullable=True, comment="指纹")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    
    # 关系
    user = relationship("User", back_populates="ssh_keys")
    
    def __repr__(self):
        return f"<SSHKey(id={self.id}, user_id={self.user_id}, name={self.name})>"

