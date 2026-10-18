"""Per-instance warnings run in reconciliation even when no browser is open."""
from datetime import timedelta
from app.models import AllocationStatus, Notice
from app.services.access_service import AccessService
from app.services.notice_service import NoticeService
from app.infrastructure.kubernetes.ephemeral_storage import pod_storage_usage
from app.core.config import settings


def refresh_temporary_storage(db, allocations, now):
    for row in allocations:
        if row.status != AllocationStatus.ACTIVE:
            continue
        try:
            sample = pod_storage_usage(row, AccessService.allocation_options(row).get('namespace', settings.K8S_NAMESPACE))
        except Exception:
            continue
        if sample['state'] != 'live':
            continue  # Absence of a measurement is not recovery.
        prefix = f'ephemeral:{row.id}:'
        level = sample['warning']
        if level == 'none':
            db.query(Notice).filter(Notice.user_id == row.user_id, Notice.dedup_key.like(prefix+'%'),
                                    Notice.expires_at > now).update({'expires_at': now}, synchronize_session=False)
            continue
        key = f'{prefix}{level}:{now.date()}'
        NoticeService.emit(db, row.user_id, key,
                           '临时磁盘空间即将耗尽' if level == 'critical' else '临时磁盘用量提醒',
                           f'实例临时磁盘已使用 {sample["used_percent"]:.1f}%，达到限额后可能被终止。请清理缓存与临时文件，将需要保留的成果保存到个人存储。',
                           link='/compute/instances?id='+row.container_id, allocation_id=row.id,
                           expires_at=now+timedelta(days=1))
        db.query(Notice).filter_by(user_id=row.user_id, dedup_key=key).update(
            {'severity': 'critical' if level == 'critical' else 'warning'}, synchronize_session=False)
