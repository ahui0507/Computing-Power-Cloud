"""Read-only detection; alerts never release a workload or change admission rules."""
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.time import utc_naive
from app.models import (
    Allocation,
    AllocationStatus,
    GPU,
    Node,
    NodeMetric,
    Notice,
    User,
    UserStatus,
)
from app.models.role import Role
from app.services.notice_service import NoticeService
from app.services.telemetry_service import TelemetryService
from app.services.maintenance_service import MaintenanceService


class OperationalAlertService:
    @staticmethod
    def refresh(db, now=None):
        if not settings.ADMIN_ALERTS_ENABLED:
            return
        now = utc_naive(now or datetime.utcnow())
        admins = [
            row[0]
            for row in db.query(User.id)
            .join(Role)
            .filter(
                Role.name == "admin",
                User.status == UserStatus.ACTIVE,
                User.deleted_at.is_(None),
            )
        ]
        active_keys = set()

        def emit(users, key, title, message, link="/admin/nodes", allocation_id=None):
            day_key = f"ops:{key}:{now.date()}"
            active_keys.add(day_key)
            for user_id in users:
                NoticeService.emit(
                    db,
                    user_id,
                    day_key,
                    title,
                    message,
                    link=link,
                    allocation_id=allocation_id,
                    expires_at=now + timedelta(days=1),
                )

        for node in db.query(Node).filter(Node.id.in_(db.query(GPU.node_id))):
            state = TelemetryService.snapshot(db, node, now=now, detail=True)
            if state["telemetry_state"] in ("missing", "stale"):
                emit(
                    admins,
                    f"node:{node.id}:stale",
                    "计算节点监控中断",
                    f"节点 {node.hostname} 未收到有效的新监控数据，请检查节点与采集服务。",
                )
                continue
            if state["gpu_error"] or state["ownership_error"]:
                emit(
                    admins,
                    f"node:{node.id}:gpu",
                    "GPU 采集异常",
                    f"节点 {node.hostname} 的 GPU 指标或占用归属采集异常，请核查。",
                )
            for gpu in state["gpu_list"]:
                if (
                    gpu["temperature"] is not None
                    and gpu["temperature"] >= settings.GPU_TEMPERATURE_ALERT_C
                ):
                    emit(
                        admins,
                        f"gpu:{gpu['gpu_id']}:hot",
                        "GPU 温度预警",
                        f"节点 {node.hostname} 的 GPU {gpu['index']} 温度达到 {gpu['temperature']}°C，请检查散热及负载。",
                    )
            # Require half an hour of continuous, attributable readings for every assigned GPU.
            samples = (
                db.query(NodeMetric)
                .filter(
                    NodeMetric.node_id == node.id,
                    NodeMetric.received_at >= now - timedelta(minutes=30),
                    NodeMetric.received_at <= now,
                )
                .order_by(NodeMetric.received_at)
                .all()
            )
            if len(samples) < 10 or utc_naive(samples[0].received_at) > now - timedelta(
                minutes=25
            ):
                continue
            times = [utc_naive(s.received_at) for s in samples] + [now]
            if any(
                (b - a).total_seconds() > settings.TELEMETRY_STALE_SECONDS
                for a, b in zip(times, times[1:])
            ):
                continue
            allocations = (
                db.query(Allocation)
                .filter_by(node_id=node.id, status=AllocationStatus.ACTIVE)
                .all()
            )
            for row in allocations:
                if (
                    not row.ready_at
                    or utc_naive(row.ready_at) > now - timedelta(minutes=30)
                    or not row.gpu_ids
                ):
                    continue
                idle = True
                for sample in samples:
                    payload = sample.payload or {}
                    metrics = {g["gpu_id"]: g for g in payload.get("gpus", [])}
                    for gpu_id in row.gpu_ids:
                        metric = metrics.get(gpu_id, {})
                        if (
                            payload.get("ownership_error")
                            or payload.get("gpu_error")
                            or not metric.get("ownership_known")
                            or metric.get("allocation_id") != row.id
                            or metric.get("utilization") is None
                            or metric["utilization"] >= 5
                        ):
                            idle = False
                            break
                    if not idle:
                        break
                if idle:
                    emit(
                        [row.user_id],
                        f"allocation:{row.id}:idle",
                        "实例 GPU 持续低利用率",
                        "过去约30分钟，该实例全部GPU利用率均低于5%。可能正在准备数据；请确认是否需要继续占用。平台不会因此自动释放实例。",
                        "/compute/instances",
                        row.id,
                    )

        backup = MaintenanceService.status()["backup"] if settings.BACKUP_ALERTS_ENABLED else {}
        if settings.BACKUP_ALERTS_ENABLED and backup.get("state") in ("failed", "error", "not_configured"):
            emit(
                admins,
                "backup:unavailable",
                "备份状态需要处理",
                "备份失败或尚未配置，请在维护中心检查。数据库备份不能代替用户文件的异机备份。",
                "/admin/maintenance",
            )
        elif settings.BACKUP_ALERTS_ENABLED:
            try:
                last_success = utc_naive(
                    datetime.fromisoformat(
                        backup.get("last_success_at", "").replace("Z", "+00:00")
                    )
                )
            except (ValueError, TypeError):
                last_success = None
            if last_success is None or now - last_success > timedelta(
                hours=settings.BACKUP_MAX_AGE_HOURS
            ):
                emit(
                    admins,
                    "backup:stale",
                    "备份已超过预期时间",
                    f"未发现最近{settings.BACKUP_MAX_AGE_HOURS}小时内的成功备份，请检查定时任务及备份目标。",
                    "/admin/maintenance",
                )
        # Resolve old warnings without deleting audit history or marking them as read.
        stale = db.query(Notice).filter(
            Notice.dedup_key.like("ops:%"), Notice.expires_at > now
        )
        if active_keys:
            stale = stale.filter(~Notice.dedup_key.in_(active_keys))
        stale.update({"expires_at": now}, synchronize_session=False)
        db.commit()
