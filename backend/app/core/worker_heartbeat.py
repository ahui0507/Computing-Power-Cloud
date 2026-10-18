"""Atomic, database-independent progress marker for the external watchdog."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import logging

from app.core.config import settings


def _record_worker_cycle(state, *, summary=None):
    if not settings.RECONCILIATION_HEARTBEAT_FILE:
        return
    path=Path(settings.RECONCILIATION_HEARTBEAT_FILE)
    previous={}
    try:
        previous=json.loads(path.read_text())
    except (OSError,ValueError):pass
    if not isinstance(previous,dict) or previous.get('pid')!=os.getpid():previous={}
    now=datetime.now(timezone.utc).isoformat()
    payload={'pid':os.getpid(),'state':state,'updated_at':now,
             'last_completed_at':previous.get('last_completed_at'),
             'errors':previous.get('errors',0)}
    if state in ('ok','degraded'):
        payload['last_completed_at']=now
        payload['errors']=int((summary or {}).get('errors',0))
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.heartbeat-',delete=False) as handle:
        temporary=Path(handle.name)
        json.dump(payload,handle);handle.flush();os.fchmod(handle.fileno(),0o644)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def record_worker_cycle(state, *, summary=None):
    try:
        _record_worker_cycle(state,summary=summary)
    except Exception:
        logging.getLogger(__name__).exception('后台心跳写入失败；资源对账仍继续执行')
