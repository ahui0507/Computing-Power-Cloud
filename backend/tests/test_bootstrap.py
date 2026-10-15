from pathlib import Path
from unittest.mock import Mock, MagicMock
import os
import sys
import subprocess

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.secret_store import load_or_create_secret
from app.core.config import settings
from app.services.readiness_service import ReadinessService
from scripts.start_backend import prepare_database


def test_empty_database_is_not_reported_healthy():
    with create_engine("sqlite://").connect() as connection:
        assert ReadinessService.check(connection)["status"] == "unhealthy"


def test_migration_and_initial_roles_are_required_for_readiness():
    with create_engine("sqlite://").connect() as connection:
        configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")
        assert ReadinessService.check(connection)["database"] == "initialization_required"
        connection.execute(text("INSERT INTO roles (id, name) VALUES (1, 'admin'), (2, 'user')"))
        assert ReadinessService.check(connection)["status"] == "healthy"


def test_startup_initializes_before_checking_readiness(monkeypatch):
    from scripts import start_backend

    database = MagicMock()
    initialized = []
    monkeypatch.setattr(settings, "AUTO_INIT_DATABASE", True)
    monkeypatch.setattr(
        start_backend.ReadinessService,
        "check",
        lambda connection: {"status": "healthy" if initialized else "unhealthy"},
    )
    prepare_database(database, lambda: initialized.append(True))
    assert initialized == [True]


def test_startup_rejects_uninitialized_database_when_auto_init_disabled(monkeypatch):
    from scripts import start_backend

    monkeypatch.setattr(settings, "AUTO_INIT_DATABASE", False)
    monkeypatch.setattr(
        start_backend.ReadinessService,
        "check",
        lambda connection: {"status": "unhealthy", "database": "migration_required"},
    )
    with pytest.raises(RuntimeError, match="migration_required"):
        prepare_database(MagicMock(), Mock())


def test_generated_secret_is_persistent_and_private(tmp_path):
    path = tmp_path / "key"
    first = load_or_create_secret(path)
    assert len(first) >= 32
    assert load_or_create_secret(path) == first


@pytest.mark.parametrize("value", ["", "REPLACE_WITH_A_CONFIRMED_SECRET_AT_LEAST_32_CHARACTERS"])
def test_unconfigured_secret_cannot_start_or_create_unrecorded_credentials(tmp_path, value):
    environment = {**os.environ, "SECRET_KEY": value, "PLATFORM_ENV_FILE": "", "STORAGE_ROOT": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", "import app.core.config"],
                            cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True)
    assert result.returncode != 0 and b"SECRET_KEY" in result.stderr
    assert not (tmp_path / ".platform-secret").exists()
