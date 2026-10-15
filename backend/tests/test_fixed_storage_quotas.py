"""Fixed limits do not shrink with membership or platform default changes."""
from unittest.mock import Mock
import pytest
from app.core.config import settings
from app.core.exceptions import ResourceConflictError
from app.models import Quota, OwnerType, User
from app.routers.monitoring import QuotaInput
from app.services.quota_service import QuotaService
from app.services.storage_quota_service import StorageQuotaService


def test_first_fixed_assignment_survives_default_change_and_new_user(db, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_QUOTA_MODE", "fixed")
    monkeypatch.setattr(settings, "STORAGE_QUOTA_ENABLED", False)
    monkeypatch.setattr(settings, "DEFAULT_STORAGE_LIMIT_GIB", 100)
    StorageQuotaService.prepare(db, 1)
    db.commit()
    monkeypatch.setattr(settings, "DEFAULT_STORAGE_LIMIT_GIB", 50)
    StorageQuotaService.prepare(db, 2)
    StorageQuotaService.prepare(db, 1)
    assert db.get(User, 1).storage_default_bytes == 100 * 1024**3
    assert db.get(User, 2).storage_default_bytes == 50 * 1024**3
    assert QuotaService.limits(db, 1)["storage_limit_gib"] == 100


def test_admin_override_changes_kernel_request_without_changing_other_user(db, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_QUOTA_MODE", "fixed")
    monkeypatch.setattr(settings, "STORAGE_QUOTA_ENABLED", True)
    helper = Mock(return_value={"used_percent": 0, "enforcement": "filesystem"})
    monkeypatch.setattr(StorageQuotaService, "helper", helper)
    StorageQuotaService.prepare(db, 1)
    QuotaService.set_limits(db, 1, QuotaInput(storage_limit_gib=200))
    assert helper.call_args.kwargs["limit_bytes"] == 200 * 1024**3
    assert QuotaService.limits(db, 2)["storage_limit_gib"] == settings.DEFAULT_STORAGE_LIMIT_GIB
    QuotaService.set_limits(db, 1, QuotaInput(inherited=True))
    assert helper.call_args.kwargs["limit_bytes"] == settings.DEFAULT_STORAGE_LIMIT_GIB * 1024**3


def test_pool_rejection_returns_conflict_without_publishing_new_limit(db, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_QUOTA_MODE", "fixed")
    monkeypatch.setattr(settings, "STORAGE_QUOTA_ENABLED", True)
    monkeypatch.setattr(StorageQuotaService, "helper", Mock(side_effect=ResourceConflictError("pool full")))
    with pytest.raises(ResourceConflictError):
        QuotaService.set_limits(db, 1, QuotaInput(storage_limit_gib=200))
    db.rollback()
    assert db.query(Quota).filter_by(owner_id=1, owner_type=OwnerType.USER).first() is None
