import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def backup(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "backup_snapshot_guards", scripts / "backup_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("report", [b"swi-a-s---:85.0", b"swi-I-s---:99.0", b"swi-a-s---:"])
def test_overflow_invalid_or_missing_snapshot_samples_fail_closed(backup, monkeypatch, report):
    monkeypatch.setattr(backup.ops, "run", lambda *args: report)
    with pytest.raises(ValueError, match="Snapshot capacity"):
        backup.snapshot_usage("/dev/vg/own_snapshot")


def test_snapshot_failure_terminates_archive_before_it_can_be_sealed(backup, monkeypatch, tmp_path):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(backup.subprocess, "Popen", lambda *args, **kwargs: process)

    def overflow(device):
        raise ValueError("Snapshot capacity is no longer safe")

    monkeypatch.setattr(backup, "snapshot_usage", overflow)
    with pytest.raises(ValueError):
        backup.archive(tmp_path, tmp_path / "backup.tar.gz", "/dev/vg/own_snapshot")
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
