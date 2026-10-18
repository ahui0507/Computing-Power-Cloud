"""Read-only, sanitized operational status for administrators."""

import json
from pathlib import Path

from app.core.config import settings
from app.services.storage_quota_service import StorageQuotaService


class MaintenanceService:
    @staticmethod
    def status():
        storage = {"enforcement": "disabled"}
        if settings.STORAGE_QUOTA_ENABLED:
            try:
                storage = StorageQuotaService.helper("health")
            except Exception:
                storage = {"enforcement": "unavailable"}
        backup = {"state": "not_configured"}
        try:
            raw = json.loads(Path(settings.BACKUP_STATUS_FILE).read_text(encoding="utf-8"))
            backup = {
                key: raw[key]
                for key in (
                    "state",
                    "started_at",
                    "finished_at",
                    "last_success_at",
                    "archive_name",
                    "retained",
                    "recovery_verified_at",
                    "message",
                )
                if key in raw
            }
        except (OSError, ValueError, TypeError):
            pass
        backup["alerts_enabled"] = settings.BACKUP_ALERTS_ENABLED
        return {"storage": storage, "backup": backup}
