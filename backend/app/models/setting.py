"""
设置模型
"""
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Setting(Base):
    """设置表（关键平台设置）"""
    __tablename__ = "settings"
    
    k = Column(String(128), primary_key=True, comment="配置键")
    v = Column(Text, nullable=True, comment="配置值")
    description = Column(String(500), nullable=True, comment="描述")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<Setting(k={self.k}, v={self.v})>"

