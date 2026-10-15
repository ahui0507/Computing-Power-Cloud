#!/usr/bin/env python3
"""Restore a verified backup into a new database and new directories, then remove the trial."""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from uuid import uuid4

import pymysql
import platform_ops as ops


def verify_files(archive, directory):
    count = 0
    with tarfile.open(archive) as source:
        for member in source:
            if member.isfile():
                path = directory / member.name
                expected = hashlib.sha256()
                with source.extractfile(member) as content:
                    for chunk in iter(lambda: content.read(1024 * 1024), b""):
                        expected.update(chunk)
                if ops.digest(path) != expected.hexdigest() or path.stat().st_uid != member.uid:
                    raise ValueError("Restored file checksum or ownership mismatch")
                count += 1
    return count


def verify(bundle, backend, status_file):
    ops.verify(bundle, "backup")
    key = uuid4().hex
    database = "platform_recovery_trial_" + key
    parent = Path("/srv/platform-recovery-trials")
    parent.mkdir(mode=0o700, exist_ok=True)
    trial = parent / key
    trial.mkdir(mode=0o700)
    connection = pymysql.connect(
        unix_socket="/var/run/mysqld/mysqld.sock", user="root", autocommit=True
    )
    created = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE `" + database + "` CHARACTER SET utf8mb4")
            created = True
        with tempfile.TemporaryFile() as sql:
            with gzip.open(bundle / "database.sql.gz", "rb") as source:
                for line in source:
                    if re.match(
                        rb"\s*(USE\s|(?:CREATE|DROP|ALTER)\s+DATABASE\s)",
                        line,
                        flags=re.I,
                    ):
                        raise ValueError("Dump attempts to select a database")
                    sql.write(line)
            sql.seek(0)
            process = subprocess.run(
                ["mysql", "--user=root", database],
                stdin=sql,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if process.returncode:
                raise ValueError("Isolated SQL restore failed")
        counts = {}
        for name, folder in (
            ("workspaces", "workspaces"),
            ("images", "images"),
            ("worker-jobs", "worker-jobs"),
        ):
            archive = bundle / (name + ".tar.gz")
            if not archive.exists():
                continue
            target = trial / folder
            ops.extract(archive, target)
            counts[name] = verify_files(archive, target)
        if (bundle / "database-summary.json").exists():
            expected = json.loads((bundle / "database-summary.json").read_text())["users"]
            with connection.cursor() as cursor:
                cursor.execute("SELECT id,email,balance FROM `" + database + "`.users ORDER BY id")
                actual = [[row[0], row[1], str(row[2])] for row in cursor.fetchall()]
            if actual != expected:
                raise ValueError("Restored user balances do not match the dump summary")
        env = {
            **os.environ,
            "PLATFORM_ENV_FILE": "",
            "DATABASE_URL": f"mysql+pymysql://root@localhost/{database}?unix_socket=/var/run/mysqld/mysqld.sock",
            "SECRET_KEY": "isolated-recovery-check-key-at-least-32-characters",
            "STORAGE_ROOT": str(trial / "workspaces"),
            "IMAGE_STORE_ROOT": str(trial / "images"),
            "STORAGE_QUOTA_ENABLED": "false",
            "RECONCILIATION_ENABLED": "false",
            "TELEMETRY_CLEANUP_ENABLED": "false",
            "WORKER_AGENT_URLS": "{}",
            "WORKER_AGENT_TOKEN": "",
            "K8S_CONFIG_PATH": str(trial / "absent-kubeconfig"),
        }
        # Rehearse pending schema upgrades against the restored copy only.
        result = subprocess.run(
            [backend / ".venv/bin/python", "-m", "alembic", "upgrade", "head"],
            env=env,
            cwd=backend,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        if result.returncode:
            raise ValueError("Isolated migration rehearsal failed")
        if (bundle / "database-summary.json").exists():
            with connection.cursor() as cursor:
                cursor.execute("SELECT id,email,balance FROM `" + database + "`.users ORDER BY id")
                after = [[row[0], row[1], str(row[2])] for row in cursor.fetchall()]
            if after != expected:
                raise ValueError("Migration changed existing user balances")
        code = """from fastapi.testclient import TestClient
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_current_user
from app.models import User, UserStatus
from app.main import app
from sqlalchemy import text
with SessionLocal() as db:
    assert db.bind.url.database.startswith('platform_recovery_trial_')
    assert not settings.RECONCILIATION_ENABLED and not settings.STORAGE_QUOTA_ENABLED
    user = db.query(User).filter(User.status==UserStatus.ACTIVE).first()
    assert user
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/storage/list').status_code == 200
        assert client.get('/resource/history').status_code == 200
        assert client.post('/storage/upload', files={'file':('recovery-only.txt',b'isolated recovery write')}).status_code == 200
    app.dependency_overrides.clear()
print('Isolated restored API read/write checks passed')
"""
        result = subprocess.run(
            [backend / ".venv/bin/python", "-c", code],
            env=env,
            cwd=backend,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        if result.returncode:
            # No secret configuration is emitted; the isolated log stays with the trial.
            ops.write(trial / "api-error.log", result.stderr.decode(errors="replace"))
            raise ValueError("Restored API checks failed")
        path = Path(status_file)
        state = json.loads(path.read_text())
        state["recovery_verified_at"] = datetime.now(timezone.utc).isoformat()
        ops.write(path.with_suffix(".tmp"), json.dumps(state, ensure_ascii=False), 0o644)
        path.with_suffix(".tmp").replace(path)
        report = {
            "verified": True,
            "archive": bundle.name,
            "files": counts,
            "balances_match": (bundle / "database-summary.json").exists(),
            "isolated_api": True,
            "trial_database_removed": True,
        }
        print(json.dumps(report))
    finally:
        if created:
            with connection.cursor() as cursor:
                cursor.execute("DROP DATABASE `" + database + "`")
        connection.close()
        if trial.parent == parent and trial.name == key:
            shutil.rmtree(trial)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--backend", default="/home/REPLACE_SERVICE_USER/platform-current/backend")
    parser.add_argument("--status-file", default="/var/lib/images/platform-data/backup-status.json")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Root required for isolated restore ownership and local database access")
    verify(Path(args.bundle).resolve(), Path(args.backend).resolve(), args.status_file)


if __name__ == "__main__":
    main()
