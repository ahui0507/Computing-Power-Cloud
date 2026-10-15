"""
集群服务
"""
from typing import Dict
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.node import Node, GPU, GPUStatus
from app.models.gpu_type import GPUType
from app.core.exceptions import ResourceNotFoundError


class ClusterService:
    """集群服务类"""
    
    @staticmethod
    def get_all_nodes(db: Session):
        """获取所有节点"""
        return db.query(Node).all()
    
    @staticmethod
    def get_node_detail(db: Session, node_id: int) -> Node:
        """获取节点详情"""
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            raise ResourceNotFoundError("Node")
        return node
    
    @staticmethod
    def get_cluster_metrics(db: Session) -> Dict:
        """获取集群监控数据"""
        from app.services.telemetry_service import TelemetryService
        snapshots = [TelemetryService.snapshot(db, node) for node in db.query(Node).all()]
        total_gpus = db.query(func.count(GPU.id)).scalar() or 0
        allocated_gpus = db.query(func.count(GPU.id)).filter(
            GPU.status.in_([GPUStatus.OCCUPIED, GPUStatus.RESERVED])
        ).scalar() or 0
        cpus = [row["cpu_usage"] for row in snapshots if row["cpu_usage"] is not None]
        return {"cluster_load": sum(cpus) / len(cpus) if cpus else None,
                "gpu_usage": allocated_gpus / total_gpus * 100 if total_gpus else 0,
                "network_in": None, "network_out": None,
                "reporting_nodes": sum(row["telemetry_state"] in ("live", "partial") for row in snapshots)}
