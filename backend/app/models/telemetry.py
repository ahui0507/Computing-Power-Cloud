"""由独立主机采集服务提交的真实指标；缺失值保留为 NULL。"""
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, JSON
from app.core.database import Base


class NodeMetric(Base):
    __tablename__ = "node_metrics"
    __table_args__ = (Index("ix_node_metrics_node_received", "node_id", "received_at"),)
    id = Column(BigInteger, primary_key=True)
    node_id = Column(BigInteger, ForeignKey("nodes.id"), nullable=False)
    collected_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    cpu_usage = Column(Float, nullable=True)
    mem_usage = Column(Float, nullable=True)
    payload = Column(JSON, nullable=False)
