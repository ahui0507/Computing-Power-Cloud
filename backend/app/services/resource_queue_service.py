"""Optional durable queue. Waiting requests reserve no GPU and incur no charge."""
from datetime import datetime, timedelta
import uuid

from sqlalchemy import or_, and_, func
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    ComputingPlatformException,
    InsufficientResourceError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.core.time import utc_iso
from app.models import Allocation, GPU, Image, ImageVisibility, UserStatus
from app.models.platform_improvements import ResourceQueue
from app.services.quota_service import QuotaService
from app.services.resource_service import ResourceService
from app.services.scheduler_service import SchedulerService
from app.services.notice_service import NoticeService


class ResourceQueueService:
    @staticmethod
    def serialize(row):
        return {
            "id": row.id,
            "status": row.status,
            "parameters": row.parameters,
            "created_at": utc_iso(row.created_at),
            "expires_at": utc_iso(row.expires_at),
            "container_id": row.container_id,
            "message": row.message,
        }

    @staticmethod
    def enqueue(db, user_id, parameters, key):
        if parameters.get("billing_mode") not in ("on_demand", "day", "week"):
            raise ResourceConflictError("请选择按时、包日或包周计费")
        parameters = {k: v for k, v in parameters.items() if v is not None}
        request_id, fingerprint = SchedulerService.request_identity(
            user_id, "queue-entry-" + key, parameters
        )
        user = QuotaService.lock_user(db, user_id)
        if user.status != UserStatus.ACTIVE or user.deleted_at:
            raise AuthorizationError("账户不可用")
        old = (
            db.query(ResourceQueue)
            .filter_by(request_id=request_id, user_id=user_id)
            .first()
        )
        if old:
            if old.fingerprint != fingerprint:
                raise ResourceConflictError("同一排队标识不能用于不同参数")
            db.rollback()
            return ResourceQueueService.serialize(old)
        image = db.get(Image, parameters["image_id"])
        if image is None:
            raise ResourceNotFoundError("镜像")
        if image.visibility != ImageVisibility.PUBLIC and image.owner_id != user_id:
            raise AuthorizationError("无权使用该私有镜像")
        if image.snapshot_status != "ready":
            raise ResourceConflictError("请选择已就绪的镜像")
        pool = ResourceService.get_pool_by_id(db, parameters["pool_id"])
        maximum = max(
            [
                count
                for _, count in db.query(GPU.node_id, func.count(GPU.id))
                .filter(
                    GPU.node_id.in_(pool.node_ids or []),
                    GPU.gpu_type_id == pool.gpu_type_id,
                )
                .group_by(GPU.node_id)
            ]
            or [0]
        )
        if parameters["gpu_count"] > maximum:
            raise ResourceConflictError("申请数量超过资源池单节点容量")
        if (
            db.query(ResourceQueue)
            .filter(
                ResourceQueue.user_id == user_id,
                ResourceQueue.status.in_(["waiting", "dispatching"]),
            )
            .count()
            >= 3
        ):
            raise ResourceConflictError("每个账号最多保留3个未完成排队申请")
        now = datetime.utcnow()
        row = ResourceQueue(
            user_id=user_id,
            request_id=request_id,
            fingerprint=fingerprint,
            parameters=parameters,
            created_at=now,
            expires_at=now + timedelta(hours=settings.RESOURCE_QUEUE_TTL_HOURS),
            status="waiting",
            message="等待资源，排队期间不占卡、不计费；分配时按当时价格和余额校验",
        )
        db.add(row)
        db.commit()
        return ResourceQueueService.serialize(row)

    @staticmethod
    def list(db, user_id):
        return [
            ResourceQueueService.serialize(row)
            for row in db.query(ResourceQueue)
            .filter_by(user_id=user_id)
            .order_by(ResourceQueue.id.desc())
            .limit(50)
        ]

    @staticmethod
    def cancel(db, user_id, queue_id):
        row = (
            db.query(ResourceQueue)
            .filter_by(id=queue_id, user_id=user_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if row is None:
            raise ResourceNotFoundError("排队申请")
        if row.status == "dispatching":
            raise ResourceConflictError("申请正在分配，请稍后查看结果；成功后可释放实例")
        if row.status == "waiting":
            row.status, row.message = "cancelled", "已取消排队，未产生费用"
            db.commit()
        return ResourceQueueService.serialize(row)

    @staticmethod
    async def run_once(db, now=None):
        now = now or datetime.utcnow()
        ids = [
            r[0]
            for r in db.query(ResourceQueue.id)
            .filter(
                or_(
                    ResourceQueue.status == "waiting",
                    and_(
                        ResourceQueue.status == "dispatching",
                        ResourceQueue.lease_until <= now,
                    ),
                )
            )
            .order_by(
                ResourceQueue.last_attempt_at,
                ResourceQueue.created_at,
                ResourceQueue.id,
            )
            .limit(settings.RECONCILIATION_BATCH_SIZE)
        ]
        for queue_id in ids:
            row = (
                db.query(ResourceQueue)
                .filter_by(id=queue_id)
                .populate_existing()
                .with_for_update()
                .one()
            )
            if row.status not in ("waiting", "dispatching") or (
                row.status == "dispatching"
                and row.lease_until
                and row.lease_until > now
            ):
                db.rollback()
                continue
            # A crash after reservation must recover that allocation even after queue expiry.
            allocation_key = "queued-allocation-" + str(queue_id)
            allocation_id, _ = SchedulerService.request_identity(
                row.user_id, allocation_key, row.parameters
            )
            existing = (
                db.query(Allocation)
                .filter_by(user_id=row.user_id, request_id=allocation_id)
                .first()
            )
            if row.expires_at <= now and existing is None:
                row.status, row.message = "expired", "排队已到期，未分配资源、未产生费用"
                NoticeService.emit(
                    db,
                    row.user_id,
                    f"queue:{row.id}:expired",
                    "排队申请已到期",
                    row.message,
                    link="/compute/instances",
                )
                db.commit()
                continue
            owner = uuid.uuid4().hex
            row.last_attempt_at = now
            row.status, row.lease_owner, row.lease_until = (
                "dispatching",
                owner,
                now + timedelta(seconds=settings.OPERATION_LEASE_SECONDS),
            )
            user_id, parameters = row.user_id, dict(row.parameters)
            db.commit()
            try:
                user = QuotaService.lock_user(db, user_id)
                if user.status != UserStatus.ACTIVE or user.deleted_at:
                    raise AuthorizationError("账户不可用")
                db.rollback()
                result = await SchedulerService.create_allocation(
                    db, user_id=user_id, idempotency_key=allocation_key, **parameters
                )
                state, message, container_id = (
                    "started",
                    "资源已分配，请到我的实例查看",
                    result["container_id"],
                )
            except InsufficientResourceError:
                db.rollback()
                state, message, container_id = (
                    "waiting",
                    "等待同一节点的空闲GPU及配套CPU/内存，排队不计费",
                    None,
                )
            except ComputingPlatformException as exc:
                db.rollback()
                # An allocation may have been committed before an RPC failed. Never create another.
                allocation = (
                    db.query(Allocation)
                    .filter_by(user_id=user_id, request_id=allocation_id)
                    .first()
                )
                if allocation:
                    state, message, container_id = (
                        "started",
                        "实例申请已登记，创建结果以我的实例为准",
                        allocation.container_id,
                    )
                elif exc.status_code >= 500:
                    state, message, container_id = (
                        "waiting",
                        "服务暂不可用，将自动重试；尚未分配资源",
                        None,
                    )
                else:
                    state, message, container_id = "failed", str(exc.detail)[:300], None
            except Exception:
                db.rollback()
                # Leave a recoverable lease for unexpected failures, then let the caller log it.
                raise
            row = (
                db.query(ResourceQueue)
                .filter_by(id=queue_id)
                .populate_existing()
                .with_for_update()
                .one()
            )
            if row.lease_owner != owner:
                db.rollback()
                continue
            row.status, row.message, row.container_id = state, message, container_id
            row.lease_owner = row.lease_until = None
            if state in ("started", "failed"):
                NoticeService.emit(
                    db,
                    user_id,
                    f"queue:{row.id}:{state}",
                    "排队申请已有结果",
                    message,
                    link="/compute/instances",
                )
            db.commit()
