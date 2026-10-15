"""
审计日志模型
"""
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"
    
    id = Column(BigInteger, primary_key=True, index=True, comment="日志ID")
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True, comment="用户ID")
    action = Column(String(128), nullable=False, comment="操作类型")
    resource_type = Column(String(64), nullable=True, comment="资源类型")
    resource_id = Column(String(64), nullable=True, comment="资源ID")
    detail = Column(JSON, nullable=True, comment="详细信息（JSON格式）")
    ip_address = Column(String(64), nullable=True, comment="IP地址")
    user_agent = Column(String(500), nullable=True, comment="User Agent")
    result = Column(String(50), default="success", nullable=False, comment="结果（success/failed）")
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="时间戳")
    
    # 关系
    user = relationship("User", backref="audit_logs")
    
    @property
    def details(self):
        """兼容旧代码"""
        return self.detail
    
    def __repr__(self):
        return f"<AuditLog(id={self.id}, user_id={self.user_id}, action={self.action}, timestamp={self.timestamp})>"

