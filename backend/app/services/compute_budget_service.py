"""Reserve a node's user budget in proportion to its total registered GPUs."""
from decimal import Decimal

from app.core.config import settings
from app.models import Allocation, GPU


class ComputeBudgetService:
    @staticmethod
    def quote(budget, gpu_count):
        total = budget["node_gpu_count"]
        if total < 1:
            return 0, 0
        return (budget["capacity_cpu_millicores"] * gpu_count // total,
                budget["capacity_ram_mb"] * gpu_count // total)

    @staticmethod
    def node_budget(db, node):
        cpu_fraction = (Decimal(100) - Decimal(str(settings.NODE_RESERVED_CPU_PERCENT))) / 100
        ram_fraction = (Decimal(100) - Decimal(str(settings.NODE_RESERVED_RAM_PERCENT))) / 100
        cpu = max(0, int(Decimal(node.cpu_cores or 0) * 1000 * cpu_fraction))
        ram = max(0, int(Decimal(str(node.memory_gb or 0)) * 1024 * ram_fraction))
        total = db.query(GPU).filter_by(node_id=node.id).count()
        held = db.query(GPU.id).filter(GPU.allocation_id == Allocation.id).exists()
        rows = db.query(Allocation).filter(Allocation.node_id == node.id,
            Allocation.compute_reserved.is_(True) | held).all()
        unknown = any(row.cpu_quota_millicores is None or row.ram_mb is None for row in rows)
        used_cpu = sum(row.cpu_quota_millicores or 0 for row in rows)
        used_ram = sum(row.ram_mb or 0 for row in rows)
        available_cpu = 0 if unknown else max(0, cpu - used_cpu)
        return {"node_gpu_count": total, "capacity_cpu_millicores": cpu,
                "capacity_cpu_cores": cpu / 1000, "capacity_ram_mb": ram,
                "reserved_cpu_millicores": used_cpu, "reserved_cpu_cores": used_cpu / 1000,
                "reserved_ram_mb": used_ram, "available_cpu_millicores": available_cpu,
                "available_cpu_cores": available_cpu / 1000,
                "available_ram_mb": 0 if unknown else max(0, ram - used_ram),
                "legacy_unbounded": unknown}

    @staticmethod
    def available_cards(budget):
        unit_cpu, unit_ram = ComputeBudgetService.quote(budget, 1)
        if unit_cpu < 1 or unit_ram < 1:
            return 0
        for count in range(budget["node_gpu_count"], 0, -1):
            cpu, ram = ComputeBudgetService.quote(budget, count)
            if cpu > 0 and ram > 0 and cpu <= budget["available_cpu_millicores"] and ram <= budget["available_ram_mb"]:
                return count
        return 0
