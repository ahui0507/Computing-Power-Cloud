"""资源操作执行器：短事务记录意图，租约控制执行，失败可以恢复。"""

import uuid
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.exceptions import ComputingPlatformException, ResourceConflictError
from app.core.time import utc_naive
from app.core.workspace import SEPARATE_LAYOUT
from app.models import Allocation, AllocationStatus, InstanceStatus
from app.models.operation import AllocationOperation, OperationKind, OperationStatus
from app.services.billing_service import BillingService
from app.services.instance_service import InstanceService
from app.services.k8s_service import K8sService
from app.services.resource_service import ResourceService


class OperationService:
    @staticmethod
    def get(db, allocation_id, kind, *, lock=False):
        query = (
            db.query(AllocationOperation)
            .filter(
                AllocationOperation.allocation_id == allocation_id,
                AllocationOperation.kind == kind,
            )
            .populate_existing()
        )
        return (query.with_for_update() if lock else query).first()

    @staticmethod
    def creation_payload(
        node,
        host,
        command,
        ssh_enabled=False,
        *,
        cpu_cores=None,
        ram_mb=None,
        cpu_millicores=None,
        gpu_count=None,
        storage_layout=SEPARATE_LAYOUT,
    ):
        return {
            "node_name": node.hostname,
            "host": host,
            "command": command,
            "namespace": settings.K8S_NAMESPACE,
            "options": {
                "namespace": settings.K8S_NAMESPACE,
                "ingress_enabled": settings.INGRESS_ENABLED,
                "ingress_host": host,
                "ingress_class": settings.INGRESS_CLASS,
                "use_tls": settings.INGRESS_USE_TLS,
                "image_pull_policy": settings.K8S_IMAGE_PULL_POLICY,
                "workspace_claim": settings.WORKSPACE_PVC_NAME,
                "storage_layout": storage_layout,
                "workspace_gid": settings.WORKSPACE_GID,
                "gpu_runtime_class": settings.K8S_GPU_RUNTIME_CLASS,
                "shared_memory_size": settings.WORKLOAD_SHM_SIZE_LIMIT,
                "nccl_p2p_disable": settings.WORKLOAD_NCCL_P2P_DISABLE,
                "isolation_enabled": settings.WORKLOAD_ISOLATION_ENABLED,
                "isolation_policy_sha256": settings.WORKLOAD_NETWORK_POLICY_SHA256,
                "cpu_cores": cpu_cores,
                "cpu_millicores": cpu_millicores,
                "ram_mb": ram_mb,
                "ephemeral_storage_gib": settings.WORKLOAD_EPHEMERAL_GIB_PER_GPU * gpu_count if gpu_count else None,
                "ssh_enabled": settings.SSH_ENABLED and ssh_enabled,
            },
            "access_host": host
            if settings.INGRESS_ENABLED or settings.CONTROL_NODE_ID
            else node.ip,
        }

    @staticmethod
    def namespace(db, allocation_id):
        created = OperationService.get(db, allocation_id, OperationKind.CREATE)
        return (
            created.payload.get("namespace", settings.K8S_NAMESPACE)
            if created
            else settings.K8S_NAMESPACE
        )

    @staticmethod
    def queue_release(db, allocation, *, billable=True, cutoff=None, final_status=None):
        db.flush()
        operation = OperationService.get(db, allocation.id, OperationKind.RELEASE, lock=True)
        if operation:
            return operation
        now = datetime.utcnow()
        allocation.release_requested_at = allocation.release_requested_at or now
        candidate = utc_naive(cutoff or allocation.release_requested_at)
        if allocation.instance and allocation.instance.stopped_at:
            candidate = min(candidate, utc_naive(allocation.instance.stopped_at))
        allocation.billing_end_time = allocation.billing_end_time or candidate
        final_status = final_status or AllocationStatus.RELEASED.value
        operation = AllocationOperation(
            allocation_id=allocation.id,
            kind=OperationKind.RELEASE,
            status=OperationStatus.PENDING,
            payload={
                "namespace": OperationService.namespace(db, allocation.id),
                "billable": billable,
                "final_status": final_status,
            },
        )
        db.add(operation)
        if final_status == AllocationStatus.RELEASED.value:
            allocation.status = AllocationStatus.RELEASING
        db.flush()
        return operation

    @staticmethod
    def _claim(db, allocation_id, kind):
        allocation = (
            db.query(Allocation)
            .filter(Allocation.id == allocation_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        operation = OperationService.get(db, allocation_id, kind, lock=True)
        now = datetime.utcnow()
        if operation is None or operation.status in (
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
        ):
            db.rollback()
            return None
        if allocation is None or (
            kind == OperationKind.CREATE and allocation.status != AllocationStatus.PENDING
        ):
            db.rollback()
            return None
        if operation.retry_at and operation.retry_at > now:
            db.rollback()
            return None
        if (
            operation.status == OperationStatus.RUNNING
            and operation.lease_until
            and operation.lease_until > now
        ):
            db.rollback()
            return None
        owner = uuid.uuid4().hex
        operation.status = OperationStatus.RUNNING
        operation.lease_owner = owner
        operation.lease_until = now + timedelta(seconds=settings.OPERATION_LEASE_SECONDS)
        operation.attempts += 1
        db.commit()
        return owner

    @staticmethod
    def _owned(db, allocation_id, kind, owner):
        allocation = (
            db.query(Allocation)
            .filter(Allocation.id == allocation_id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        operation = OperationService.get(db, allocation_id, kind, lock=True)
        if (
            operation is None
            or operation.status != OperationStatus.RUNNING
            or operation.lease_owner != owner
        ):
            db.rollback()
            raise ResourceConflictError("操作已由其他执行器接管，请查询实例状态")
        if allocation.instance:
            db.refresh(allocation.instance)
        return allocation, operation

    @staticmethod
    def _complete(operation):
        operation.status = OperationStatus.SUCCEEDED
        operation.lease_owner = None
        operation.lease_until = None
        operation.retry_at = None
        operation.error_code = None
        operation.error_message = None

    @staticmethod
    def _error(operation, error):
        operation.error_code = (
            error.status_code if isinstance(error, ComputingPlatformException) else 500
        )
        operation.error_message = (
            str(error.detail)[:512]
            if isinstance(error, ComputingPlatformException)
            else "资源操作执行失败"
        )

    @staticmethod
    async def execute_create(db, allocation_id):
        owner = OperationService._claim(db, allocation_id, OperationKind.CREATE)
        if owner is None:
            return False
        allocation = db.get(Allocation, allocation_id)
        operation = OperationService.get(db, allocation_id, OperationKind.CREATE)
        payload = dict(operation.payload)
        options = dict(payload.get("options") or {})
        if options.get("ssh_enabled"):
            from app.models.ssh_key import SSHKey

            options["ssh_authorized_keys"] = (
                "\n".join(
                    row.public_key
                    for row in db.query(SSHKey).filter_by(user_id=allocation.user_id).all()
                )
                + "\n"
            )
        try:
            result = await K8sService.create_pod(
                allocation=allocation,
                image=allocation.image_name,
                gpu_count=allocation.requested_gpu_count,
                node_name=payload["node_name"],
                host=payload["host"],
                command=payload["command"],
                options=options,
            )
            if result.get("error"):
                from app.core.exceptions import ClusterOperationError

                raise ClusterOperationError(str(result["error"]))
        except Exception as error:
            db.rollback()
            allocation, operation = OperationService._owned(
                db, allocation_id, OperationKind.CREATE, owner
            )
            operation.status = OperationStatus.FAILED
            operation.lease_owner = None
            operation.lease_until = None
            OperationService._error(operation, error)
            allocation.status = AllocationStatus.FAILED
            if allocation.instance:
                allocation.instance.status = InstanceStatus.ERROR
                allocation.instance.status_message = operation.error_message
            if getattr(error, "cleanup_confirmed", False):
                BillingService.finish_package(db, allocation, datetime.utcnow(), billable=False)
                ResourceService.release_gpus(db, allocation)
            else:
                OperationService.queue_release(
                    db, allocation, billable=False, final_status=AllocationStatus.FAILED.value
                )
            db.commit()
            if not getattr(error, "cleanup_confirmed", False):
                try:
                    await OperationService.execute_release(db, allocation_id)
                except Exception:
                    # 操作日志保留重试计划，当前接口返回原始创建错误。
                    db.rollback()
            raise

        # 远程已成功但本地提交失败时不删除工作负载，租约过期后恢复同一操作。
        try:
            allocation, operation = OperationService._owned(
                db, allocation_id, OperationKind.CREATE, owner
            )
            for field in ("ssh_port", "vnc_port", "jupyter_port"):
                value = result.get(field) or None
                setattr(allocation, field, value)
                if allocation.instance:
                    setattr(allocation.instance, field, value)
            InstanceService.apply_snapshot(
                allocation,
                result.get("status", "pending"),
                started_at=result.get("started_at"),
                finished_at=result.get("finished_at"),
                message=result.get("status_message"),
            )
            BillingService.start_package(db, allocation)
            allocation.last_observed_at = datetime.utcnow()
            OperationService._complete(operation)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return True

    @staticmethod
    async def execute_release(db, allocation_id):
        owner = OperationService._claim(db, allocation_id, OperationKind.RELEASE)
        if owner is None:
            return False
        allocation = db.get(Allocation, allocation_id)
        operation = OperationService.get(db, allocation_id, OperationKind.RELEASE)
        namespace = operation.payload.get("namespace", settings.K8S_NAMESPACE)
        try:
            snapshot = (
                await K8sService.get_pod_status(allocation.pod_name, namespace=namespace)
                if allocation.pod_name
                else None
            )
            allocation, operation = OperationService._owned(
                db, allocation_id, OperationKind.RELEASE, owner
            )
            if snapshot is not None:
                InstanceService.update_runtime(allocation, snapshot)
                if allocation.instance and allocation.instance.stopped_at:
                    allocation.billing_end_time = min(
                        allocation.billing_end_time, utc_naive(allocation.instance.stopped_at)
                    )
            operation.lease_until = datetime.utcnow() + timedelta(
                seconds=settings.OPERATION_LEASE_SECONDS
            )
            db.commit()  # 在删除之前持久化运行时间和截止时间。
        except Exception as error:
            db.rollback()
            OperationService.retry_release(db, allocation_id, owner, error)
            raise

        try:
            if allocation.pod_name:
                await K8sService.delete_pod(
                    allocation.pod_name, user_id=allocation.user_id, namespace=namespace
                )
        except Exception as error:
            db.rollback()
            OperationService.retry_release(db, allocation_id, owner, error)
            raise

        try:
            allocation, operation = OperationService._owned(
                db, allocation_id, OperationKind.RELEASE, owner
            )
            cutoff = allocation.billing_end_time or allocation.release_requested_at
            if operation.payload.get("billable", True):
                BillingService.settle_allocation(db, allocation, cutoff)
            else:
                BillingService.finish_package(db, allocation, cutoff, billable=False)
            ResourceService.release_gpus(db, allocation)
            allocation.status = AllocationStatus(operation.payload.get("final_status", "released"))
            allocation.end_time = cutoff
            if allocation.instance:
                allocation.instance.status = (
                    InstanceStatus.TERMINATED
                    if allocation.status == AllocationStatus.RELEASED
                    else InstanceStatus.STOPPED
                    if allocation.status == AllocationStatus.STOPPED
                    else InstanceStatus.ERROR
                )
                allocation.instance.stopped_at = cutoff
            OperationService._complete(operation)
            db.commit()
        except Exception:
            # 删除已确认而结算失败，持久化的租约和截止时间供下次恢复使用。
            db.rollback()
            raise
        return True

    @staticmethod
    def retry_release(db, allocation_id, owner, error):
        _, operation = OperationService._owned(db, allocation_id, OperationKind.RELEASE, owner)
        OperationService._error(operation, error)
        operation.status = OperationStatus.PENDING
        operation.lease_owner = None
        operation.lease_until = None
        delay = min(settings.OPERATION_RETRY_SECONDS * 2 ** min(operation.attempts - 1, 5), 300)
        operation.retry_at = datetime.utcnow() + timedelta(seconds=delay)
        db.commit()
