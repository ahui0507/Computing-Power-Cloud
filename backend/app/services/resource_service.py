"""资源查询与预留；事务由调用业务服务提交。"""
from sqlalchemy import func, case, and_
from datetime import datetime
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import InsufficientResourceError, ResourceNotFoundError
from app.models.allocation import Allocation, AllocationStatus
from app.models.node import GPU, GPUStatus, Node, NodeStatus
from app.models.resource_pool import ResourcePool
from app.core.config import settings
from app.services.compute_budget_service import ComputeBudgetService


def eligible_nodes(db):
    if not settings.TELEMETRY_ENFORCE_FRESHNESS:
        return [row.id for row in db.query(Node).filter(Node.status == NodeStatus.ONLINE)]
    from app.services.telemetry_service import TelemetryService
    return TelemetryService.eligible_node_ids(db)


class ResourceService:
    @staticmethod
    def get_summary(db):
        available = eligible_nodes(db)
        total, free, used = db.query(
            func.count(GPU.id),
            func.sum(case((and_(GPU.status == GPUStatus.FREE, GPU.node_id.in_(available)), 1), else_=0)),
            func.sum(case((GPU.status.in_([GPUStatus.OCCUPIED, GPUStatus.RESERVED]), 1), else_=0)),
        ).join(Node, GPU.node_id == Node.id).one()
        free = sum(min(count, ComputeBudgetService.available_cards(ComputeBudgetService.node_budget(db, db.get(Node, node_id))))
            for node_id, count in db.query(GPU.node_id, func.count(GPU.id)).filter(
                GPU.node_id.in_(available), GPU.status == GPUStatus.FREE).group_by(GPU.node_id))
        used = int(used or 0)
        return {"total_gpus": total, "free_gpus": free, "used_gpus": used,
                "unavailable_gpus": total - free - used}

    @staticmethod
    def get_pools(db):
        # 读取资源池不更新数据库中的缓存字段。
        return db.query(ResourcePool).options(joinedload(ResourcePool.gpu_type_obj)).all()

    @staticmethod
    def _calculate_total_gpus(db, pool):
        return (
            db.query(func.count(GPU.id))
            .filter(GPU.node_id.in_(pool.node_ids or []), GPU.gpu_type_id == pool.gpu_type_id)
            .scalar()
            or 0
        )

    @staticmethod
    def _calculate_free_gpus(db, pool):
        return ResourceService.pool_capacity(db, pool)["free_gpus"]

    @staticmethod
    def pool_capacity(db, pool):
        allowed = set(eligible_nodes(db))
        result = {"ephemeral_storage_gib_per_gpu": settings.WORKLOAD_EPHEMERAL_GIB_PER_GPU, "free_gpus": 0, "physical_free_gpus": 0, "max_gpus_per_instance": 0,
                  "available_cpu_cores": 0, "available_ram_mb": 0,
                  "cpu_cores_per_gpu": None, "ram_mb_per_gpu": None, "node_gpu_count": None,
                  "system_cpu_percent": settings.NODE_RESERVED_CPU_PERCENT,
                  "system_ram_percent": settings.NODE_RESERVED_RAM_PERCENT}
        profiles = []
        for node in db.query(Node).filter(Node.id.in_(pool.node_ids or [])):
            physical = db.query(GPU).filter_by(node_id=node.id, gpu_type_id=pool.gpu_type_id, status=GPUStatus.FREE).count()
            result["physical_free_gpus"] += physical
            if node.id not in allowed:
                continue
            budget = ComputeBudgetService.node_budget(db, node)
            profiles.append((budget["node_gpu_count"], *ComputeBudgetService.quote(budget, 1)))
            cards = min(physical, ComputeBudgetService.available_cards(budget))
            result["free_gpus"] += cards
            result["max_gpus_per_instance"] = max(result["max_gpus_per_instance"], cards)
            result["available_cpu_cores"] += budget["available_cpu_cores"]
            result["available_ram_mb"] += budget["available_ram_mb"]
        if profiles and len({profile[0] for profile in profiles}) == 1:
            result["node_gpu_count"] = profiles[0][0]
        if profiles and len(set(profiles)) == 1:
            result["cpu_cores_per_gpu"] = profiles[0][1] / 1000
            result["ram_mb_per_gpu"] = profiles[0][2]
        return result

    @staticmethod
    def get_pool_by_id(db, pool_id: int, *, lock=False):
        pool = (db.query(ResourcePool).filter_by(id=pool_id).populate_existing().with_for_update().first()
                if lock else db.get(ResourcePool, pool_id))
        if pool is None:
            raise ResourceNotFoundError("Resource pool")
        return pool

    @staticmethod
    def find_available_gpus(db, pool_id: int, gpu_count: int):
        if gpu_count < 1:
            raise InsufficientResourceError("GPU 数量必须大于零")
        pool = ResourceService.get_pool_by_id(db, pool_id)
        allowed = set(eligible_nodes(db))
        for node_id in sorted(pool.node_ids or []):
            # Lock order is pool -> node -> GPU. The caller locks the pool before
            # inserting allocation FKs, avoiding shared-to-exclusive lock upgrades.
            node = db.query(Node).filter_by(id=node_id).populate_existing().with_for_update().first()
            if not node or node_id not in allowed:
                continue
            if ComputeBudgetService.available_cards(ComputeBudgetService.node_budget(db, node)) < gpu_count:
                continue
            gpus = (
                db.query(GPU)
                .filter(
                    GPU.node_id == node_id,
                    GPU.gpu_type_id == pool.gpu_type_id,
                    GPU.status == GPUStatus.FREE,
                )
                .order_by(GPU.id)
                .limit(gpu_count)
                .with_for_update(skip_locked=True)
                .all()
            )
            if len(gpus) == gpu_count:
                return node, gpus
        raise InsufficientResourceError(f"没有同一节点可同时提供 {gpu_count} 张 GPU 及配套 CPU/内存，请减少数量或等待资源释放")

    @staticmethod
    def _refresh_counts(db, allocation):
        db.flush()
        node = db.get(Node, allocation.node_id)
        if node:
            node.gpus_free = (
                db.query(func.count(GPU.id))
                .filter(GPU.node_id == node.id, GPU.status == GPUStatus.FREE)
                .scalar()
                or 0
            )
        if allocation.pool_id:
            pool = db.get(ResourcePool, allocation.pool_id)
            if pool:
                pool.free_gpus = ResourceService._calculate_free_gpus(db, pool)

    @staticmethod
    def allocate_gpus(db, gpus, allocation):
        allocation.compute_reserved = True
        for gpu in gpus:
            gpu.status = GPUStatus.OCCUPIED
            gpu.occupied_by = allocation.user_id
            gpu.allocation_id = allocation.id
        ResourceService._refresh_counts(db, allocation)

    @staticmethod
    def release_gpus(db, allocation):
        # 按当前所有者释放，历史申请不能释放已分配给其他申请的 GPU。
        if allocation.pool_id:
            ResourceService.get_pool_by_id(db, allocation.pool_id, lock=True)
        db.query(Node).filter_by(id=allocation.node_id).with_for_update().first()
        gpus = db.query(GPU).filter(GPU.allocation_id == allocation.id).with_for_update().all()
        for gpu in gpus:
            gpu.status = GPUStatus.FREE
            gpu.occupied_by = None
            gpu.allocation_id = None
        allocation.compute_reserved = False
        ResourceService._refresh_counts(db, allocation)

    @staticmethod
    def get_user_allocations(db, user_id: int):
        query = (db.query(Allocation)
            .options(
                joinedload(Allocation.instance),
                joinedload(Allocation.node),
                selectinload(Allocation.operations),
                selectinload(Allocation.billing_records),
            )
            .filter(Allocation.user_id == user_id)
        )
        current = [AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE, AllocationStatus.RELEASING]
        active = query.filter(Allocation.status.in_(current)).all()
        history = query.filter(~Allocation.status.in_(current)).order_by(Allocation.created_at.desc(), Allocation.id.desc()).limit(10).all()
        return sorted(active + history, key=lambda row: (row.created_at or datetime.min, row.id), reverse=True)

    @staticmethod
    def get_history(db, user):
        current = [AllocationStatus.PENDING, AllocationStatus.APPROVED, AllocationStatus.ACTIVE, AllocationStatus.RELEASING]
        query = db.query(Allocation).options(joinedload(Allocation.instance), joinedload(Allocation.user), joinedload(Allocation.node),
            selectinload(Allocation.operations), selectinload(Allocation.billing_records)).filter(~Allocation.status.in_(current))
        if user.role != "admin":
            query = query.filter(Allocation.user_id == user.id)
        query = query.order_by(Allocation.created_at.desc(), Allocation.id.desc())
        return query.all() if user.role == "admin" else query.limit(10).all()
