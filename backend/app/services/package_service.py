"""已付费时间包到期后回收；保存中的镜像沿用原任务超时，费用不增加。"""
from datetime import datetime

from app.core.time import utc_naive
from app.models import Allocation, AllocationStatus, AuditLog, Image


class PackageService:
    @staticmethod
    def expire(db, now=None):
        from app.services.operation_service import OperationService
        now = utc_naive(now or datetime.utcnow())
        ids = [row[0] for row in db.query(Allocation.id).filter(
            Allocation.package_expires_at <= now,
            Allocation.status.in_([AllocationStatus.ACTIVE, AllocationStatus.APPROVED])).order_by(Allocation.id).all()]
        for allocation_id in ids:
            allocation = db.query(Allocation).filter_by(id=allocation_id).populate_existing().with_for_update().one()
            if allocation.status not in (AllocationStatus.ACTIVE, AllocationStatus.APPROVED):
                db.rollback()
                continue
            if db.query(Image.id).filter_by(source_container_id=allocation.container_id, snapshot_status="saving").first():
                db.commit()
                continue
            OperationService.queue_release(db, allocation, cutoff=utc_naive(allocation.package_expires_at))
            if allocation.instance:
                allocation.instance.status_message = "包时已到期，自动释放；个人文件继续保留"
            db.add(AuditLog(user_id=allocation.user_id, action="包时到期自动释放", resource_type="allocation", resource_id=str(allocation.id), result="success"))
            db.commit()
