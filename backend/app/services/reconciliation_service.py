"""从持久化操作恢复执行，并核对数据库与集群状态。"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, and_

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import (
    Allocation,
    AllocationStatus,
    GPU,
    Image,
    Node,
    Instance,
    InstanceStatus,
)
from app.models.operation import AllocationOperation, OperationKind, OperationStatus
from app.services.access_service import AccessService
from app.services.instance_service import InstanceService
from app.services.k8s_service import K8sService
from app.services.operation_service import OperationService

logger = logging.getLogger(__name__)


class ReconciliationService:
    @staticmethod
    def recover_legacy(db, limit):
        rows = (
            db.query(Allocation)
            .filter(
                Allocation.status == AllocationStatus.PENDING,
                ~Allocation.operations.any(AllocationOperation.kind == OperationKind.CREATE),
            )
            .order_by(Allocation.id)
            .limit(limit)
            .all()
        )
        for allocation in rows:
            node = db.get(Node, allocation.node_id)
            image = db.get(Image, allocation.image_id)
            if node is None or image is None:
                allocation.status = AllocationStatus.FAILED
                if allocation.instance:
                    allocation.instance.status = InstanceStatus.ERROR
                    allocation.instance.status_message = "旧申请缺少节点或镜像信息，需要核对"
                continue
            allocation.container_id = (
                allocation.container_id or f"container-{allocation.id}-recovered"
            )
            allocation.pod_name = (
                allocation.pod_name or f"pod-{allocation.id}-{allocation.container_id[:8]}"
            )
            if allocation.instance is None:
                db.add(
                    Instance(
                        allocation=allocation,
                        instance_name=allocation.container_id,
                        node_id=node.id,
                        gpu_ids=allocation.gpu_ids or [],
                        image_id=image.id,
                        status=InstanceStatus.CREATING,
                    )
                )
            db.add(
                AllocationOperation(
                    allocation_id=allocation.id,
                    kind=OperationKind.CREATE,
                    status=OperationStatus.PENDING,
                    attempts=1,
                    created_at=allocation.created_at,
                    payload=OperationService.creation_payload(
                        node,
                        AccessService.get_jupyter_host(db),
                        image.startup_command or settings.JUPYTER_COMMAND,
                        storage_layout="legacy",
                    ),
                )
            )
        if rows:
            db.commit()

    @staticmethod
    async def observe(db, allocation_id):
        allocation = db.get(Allocation, allocation_id)
        if allocation is None or allocation.status not in (
            AllocationStatus.APPROVED,
            AllocationStatus.ACTIVE,
        ):
            return
        namespace = OperationService.namespace(db, allocation_id)
        snapshot = await K8sService.get_pod_status(allocation.pod_name, namespace=namespace)
        allocation = (
            db.query(Allocation)
            .filter(Allocation.id == allocation_id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        if allocation.instance:
            db.refresh(allocation.instance)
        if allocation.status not in (
            AllocationStatus.APPROVED,
            AllocationStatus.ACTIVE,
        ):
            db.rollback()
            return
        now = datetime.utcnow()
        allocation.last_reconciled_at = now
        if snapshot is None:
            # 404 才认定对象消失；连接错误不会进入此分支。
            cutoff = allocation.last_observed_at or allocation.start_time or now
            OperationService.queue_release(db, allocation, cutoff=cutoff)
            if allocation.instance:
                allocation.instance.status_message = "工作负载已不存在，正在完成资源回收"
        else:
            # 旧版在创建 Pod 后就标记 active，迁移回填的 ready_at 不代表已真正运行。
            # 只在从未成功观测且 kubelet 明确拒绝启动时免除这笔历史费用。
            unobserved_admission_failure = (
                getattr(snapshot, "admission_rejected", False)
                and allocation.last_observed_at is None
            )
            InstanceService.apply_snapshot(allocation, snapshot)
            from app.services.billing_service import BillingService

            BillingService.start_package(db, allocation)
            timeout = allocation.created_at and now - allocation.created_at > timedelta(
                seconds=settings.WORKLOAD_STARTUP_TIMEOUT_SECONDS
            )
            if snapshot == "pending" and timeout and allocation.ready_at is None:
                allocation.status = AllocationStatus.FAILED
                if allocation.instance:
                    allocation.instance.status = InstanceStatus.ERROR
                    allocation.instance.status_message = "实例启动超时，正在清理预留资源"
                OperationService.queue_release(
                    db, allocation, billable=False, final_status="failed"
                )
            elif snapshot in ("failed", "stopped"):
                OperationService.queue_release(
                    db,
                    allocation,
                    billable=allocation.ready_at is not None and not unobserved_admission_failure,
                    final_status="failed" if snapshot == "failed" else "stopped",
                )
        db.commit()

    @staticmethod
    async def run_once(db):
        from app.services.image_service import ImageService
        from app.services.debt_service import DebtService
        from app.services.package_service import PackageService

        ImageService.reconcile_saves(db)
        from app.services.release_schedule_service import ReleaseScheduleService
        ReleaseScheduleService.expire(db)
        PackageService.expire(db)
        await DebtService.run_once(db)
        from app.models.platform_improvements import LoginThrottle
        db.query(LoginThrottle).filter(LoginThrottle.window_start < datetime.utcnow() - timedelta(days=1)).delete(synchronize_session=False)
        db.commit()
        limit = settings.RECONCILIATION_BATCH_SIZE
        ReconciliationService.recover_legacy(db, limit)
        now = datetime.utcnow()
        operations = (
            db.query(AllocationOperation)
            .filter(
                or_(
                    AllocationOperation.status == OperationStatus.PENDING,
                    and_(
                        AllocationOperation.status == OperationStatus.RUNNING,
                        or_(
                            AllocationOperation.lease_until.is_(None),
                            AllocationOperation.lease_until <= now,
                        ),
                    ),
                ),
                or_(
                    AllocationOperation.retry_at.is_(None),
                    AllocationOperation.retry_at <= now,
                ),
            )
            .order_by(AllocationOperation.created_at, AllocationOperation.id)
            .limit(limit)
            .all()
        )
        summary = {"processed": 0, "observed": 0, "errors": 0}
        for operation in operations:
            allocation_id, kind = operation.allocation_id, operation.kind
            try:
                allocation = db.get(Allocation, allocation_id)
                if kind == OperationKind.CREATE:
                    age = now - operation.created_at
                    if age > timedelta(seconds=settings.WORKLOAD_STARTUP_TIMEOUT_SECONDS):
                        snapshot = await K8sService.get_pod_status(
                            allocation.pod_name,
                            namespace=operation.payload.get("namespace", settings.K8S_NAMESPACE),
                        )
                        if snapshot != "running":
                            allocation = (
                                db.query(Allocation)
                                .filter(Allocation.id == allocation_id)
                                .populate_existing()
                                .with_for_update()
                                .one()
                            )
                            current = OperationService.get(
                                db, allocation_id, OperationKind.CREATE, lock=True
                            )
                            if allocation.status != AllocationStatus.PENDING or current.status in (
                                OperationStatus.SUCCEEDED,
                                OperationStatus.FAILED,
                            ):
                                db.rollback()
                                continue
                            if (
                                current.status == OperationStatus.RUNNING
                                and current.lease_until
                                and current.lease_until > datetime.utcnow()
                            ):
                                db.rollback()
                                continue
                            current.status = OperationStatus.FAILED
                            current.lease_owner = None
                            current.lease_until = None
                            current.error_code = 409
                            current.error_message = "创建操作超时，正在清理预留资源"
                            allocation.status = AllocationStatus.FAILED
                            if allocation.instance:
                                allocation.instance.status = InstanceStatus.ERROR
                                allocation.instance.status_message = current.error_message
                            OperationService.queue_release(
                                db, allocation, billable=False, final_status="failed"
                            )
                            db.commit()
                            await OperationService.execute_release(db, allocation_id)
                            summary["processed"] += 1
                            continue
                    completed = await OperationService.execute_create(db, allocation_id)
                else:
                    completed = await OperationService.execute_release(db, allocation_id)
                summary["processed"] += int(completed)
            except Exception:
                db.rollback()
                summary["errors"] += 1
                logger.exception(
                    "资源操作恢复失败: allocation=%s kind=%s", allocation_id, kind.value
                )

        # 轮转核对长期活跃的记录，防止前一批实例一直占据整个扫描批次。
        rows = (
            db.query(Allocation)
            .filter(Allocation.status.in_([AllocationStatus.APPROVED, AllocationStatus.ACTIVE]))
            .order_by(Allocation.last_reconciled_at, Allocation.id)
            .limit(limit)
            .all()
        )
        for allocation in rows:
            allocation_id = allocation.id
            try:
                await ReconciliationService.observe(db, allocation_id)
                summary["observed"] += 1
            except Exception:
                db.rollback()
                allocation = db.get(Allocation, allocation_id)
                allocation.last_reconciled_at = datetime.utcnow()
                if allocation.instance:
                    allocation.instance.status_message = "集群状态暂不可查询，保留最近已确认状态"
                db.commit()
                summary["errors"] += 1
                logger.exception("实例状态核对失败: allocation=%s", allocation_id)

        failed = (
            db.query(Allocation)
            .filter(
                Allocation.status.in_(
                    [
                        AllocationStatus.FAILED,
                        AllocationStatus.STOPPED,
                        AllocationStatus.RELEASING,
                    ]
                ),
                db.query(GPU.id).filter(GPU.allocation_id == Allocation.id).exists(),
                ~Allocation.operations.any(AllocationOperation.kind == OperationKind.RELEASE),
            )
            .limit(limit)
            .all()
        )
        for allocation in failed:
            OperationService.queue_release(
                db,
                allocation,
                billable=allocation.ready_at is not None
                or allocation.status == AllocationStatus.RELEASING,
                final_status="released"
                if allocation.status == AllocationStatus.RELEASING
                else allocation.status.value,
            )
        if failed:
            db.commit()
        try:
            from app.services.notice_service import NoticeService

            NoticeService.refresh(db)
            from app.services.operational_alert_service import OperationalAlertService
            OperationalAlertService.refresh(db)
        except Exception:
            db.rollback()
            logger.exception("站内提醒刷新失败")
        try:
            from app.services.resource_queue_service import ResourceQueueService
            await ResourceQueueService.run_once(db)
        except Exception:
            db.rollback()
            logger.exception("排队申请调度失败")
        return summary


def run_reconciliation_once(session_factory=SessionLocal):
    with session_factory() as db:
        return asyncio.run(ReconciliationService.run_once(db))


async def reconciliation_loop(stop_event):
    while not stop_event.is_set():
        try:
            from app.core.worker_heartbeat import record_worker_cycle
            record_worker_cycle('running')
            # Session 及同步 SQL 全部留在该线程，不阻塞 API 事件循环。
            summary = await asyncio.to_thread(run_reconciliation_once)
            record_worker_cycle('degraded' if summary.get('errors') else 'ok', summary=summary)
        except Exception:
            try:
                record_worker_cycle('error')
            except Exception:
                logger.exception("后台进度记录失败")
            logger.exception("后台对账周期执行失败")
        try:
            await asyncio.wait_for(stop_event.wait(), settings.RECONCILIATION_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
