#!/usr/bin/env python3
"""Online disk backup using a short MySQL read lock and a monitored LVM snapshot."""

import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from uuid import uuid4

import pymysql
import platform_ops as ops


def now():
    return datetime.now(timezone.utc).isoformat()


def status(cfg, **changes):
    path = Path(cfg["status_file"])
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    previous.update(changes)
    temporary = path.with_suffix(".tmp")
    ops.write(temporary, json.dumps(previous, ensure_ascii=False), 0o644)
    temporary.replace(path)


def snapshot_usage(device):
    fields = (
        ops.run(
            [
                "lvs",
                "--noheadings",
                "--separator",
                ":",
                "-o",
                "lv_attr,data_percent",
                device,
            ]
        )
        .decode()
        .strip()
        .split(":")
    )
    if len(fields) != 2 or not fields[1].strip() or "I" in fields[0] or float(fields[1]) >= 85:
        raise ValueError("Snapshot capacity is no longer safe")


def archive(source, destination, snapshot):
    process = subprocess.Popen(
        [
            "tar",
            "--numeric-owner",
            "--one-file-system",
            "-I",
            "gzip -1",
            "-cpf",
            str(destination),
            "-C",
            str(source),
            ".",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 1800
        while process.poll() is None:
            snapshot_usage(snapshot)
            if time.monotonic() > deadline:
                raise ValueError("Archive timed out")
            time.sleep(2)
        if process.returncode:
            raise ValueError("Archive failed")
        snapshot_usage(snapshot)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def backup(cfg):
    data = Path(cfg["data_mount"])
    destination = Path(cfg["archive_root"])
    if not data.is_mount() or not destination.is_mount():
        raise ValueError("Both data and remote backup volumes must be mounted")
    site = ops.load_site(cfg["site_file"])
    backend = Path(cfg["backend"]).resolve()
    state = ops.backend_state(backend)
    if state["database_name"] != site["database_name"]:
        raise ValueError("Database configuration mismatch")
    key = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = destination / (".incomplete-" + key)
    output.mkdir(mode=0o700)
    mount = Path("/run/platform-backup-" + key)
    mount.mkdir(mode=0o700)
    lv_name = "platform_bak_" + uuid4().hex[:12]
    device = "/dev/" + cfg["volume_group"] + "/" + lv_name
    created = mounted = False
    connection = None
    status(cfg, state="running", started_at=now(), message="正在生成磁盘时点备份。")
    try:
        free = int(
            ops.run(["vgs", "--noheadings", "-o", "vg_free_count", cfg["volume_group"]])
            .decode()
            .strip()
        )
        ops.run(["modprobe", "dm_snapshot"])
        extents = int(free * 0.4)
        if extents < 256:
            raise ValueError("Not enough free extents for a snapshot")
        connection = pymysql.connect(
            unix_socket="/var/run/mysqld/mysqld.sock",
            user="root",
            autocommit=True,
            read_timeout=120,
            write_timeout=120,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION lock_wait_timeout=10")
            cursor.execute("FLUSH TABLES WITH READ LOCK")
            cursor.execute(
                "SELECT COUNT(*) FROM `"
                + site["database_name"]
                + "`.images WHERE snapshot_status IN (%s,%s)",
                ("saving", "deleting"),
            )
            if cursor.fetchone()[0]:
                status(
                    cfg,
                    state="deferred",
                    finished_at=now(),
                    message="镜像任务进行中，下一周期会自动重试。",
                )
                return
            if cfg.get("worker_journal_root"):
                journal = Path(cfg["worker_journal_root"])
                if not journal.is_mount():
                    raise ValueError("Worker image journal export is not mounted")
                ops.run(
                    [
                        "tar",
                        "--numeric-owner",
                        "-czpf",
                        output / "worker-jobs.tar.gz",
                        "-C",
                        journal,
                        ".",
                    ]
                )
            with tempfile.TemporaryFile() as sql:
                ops.run(
                    [
                        "mysqldump",
                        "--user=root",
                        "--single-transaction",
                        "--hex-blob",
                        "--no-tablespaces",
                        site["database_name"],
                    ],
                    stdout=sql,
                )
                sql.seek(0)
                with gzip.open(output / "database.sql.gz", "wb") as zipped:
                    shutil.copyfileobj(sql, zipped)
            # Lock-held inventory describes the same committed database as the dump.
            state = ops.backend_state(backend)
            cursor.execute(
                "SELECT id,email,balance FROM `" + site["database_name"] + "`.users ORDER BY id"
            )
            summary = [[row[0], row[1], str(row[2])] for row in cursor.fetchall()]
            ops.write(output / "database-summary.json", json.dumps({"users": summary}))
            # LVM suspends and flushes the origin filesystem itself. An external
            # fsfreeze conflicts with device-mapper's freeze on this kernel.
            result = subprocess.run(
                [
                    "lvcreate",
                    "--snapshot",
                    "--extents",
                    str(extents),
                    "--name",
                    lv_name,
                    cfg["device"],
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            created = (
                subprocess.run(
                    ["lvs", device],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
            if result.returncode:
                raise ValueError(
                    "Snapshot creation failed: " + result.stderr.decode(errors="replace")[-800:]
                )
            cursor.execute("UNLOCK TABLES")
        connection.close()
        connection = None
        ops.run(["mount", "-o", "ro,noload", device, mount])
        mounted = True
        for source, target in (
            (cfg["workspace_relative"], "workspaces.tar.gz"),
            (cfg["images_relative"], "images.tar.gz"),
        ):
            path = mount / source
            if not ops.within(path, mount) or not path.is_dir():
                raise ValueError("Invalid snapshot source")
            archive(path, output / target, device)
        shutil.copyfile(backend / ".env", output / "backend.env")
        (output / "backend.env").chmod(0o600)
        ops.write(output / "inventory.json", json.dumps(state, ensure_ascii=False))
        ops.write(output / "site.json", json.dumps(site, ensure_ascii=False))
        ops.seal(
            output,
            "backup",
            {
                "snapshot_at": key,
                "consistency": "database-and-disk; running process memory excluded",
            },
        )
        ops.verify(output, "backup")
        final = destination / key
        output.rename(final)
        completed = []
        for path in sorted(destination.iterdir(), reverse=True):
            if path.is_dir() and not path.is_symlink() and (path / "manifest.json").is_file():
                try:
                    ops.verify(path, "backup")
                    completed.append(path)
                except ValueError:
                    continue
        for path in completed[cfg.get("retention", 3) :]:
            shutil.rmtree(path)
        status(
            cfg,
            state="ready",
            finished_at=now(),
            last_success_at=now(),
            archive_name=key,
            retained=min(len(completed), cfg.get("retention", 3)),
            message="数据库、个人文件和镜像归档已校验并保存。",
        )
        print(json.dumps({"backup": key, "verified": True}))
    finally:
        if connection:
            connection.close()  # Always release the database lock.
        if mounted:
            ops.run(["umount", mount])
        if created:
            ops.run(["lvremove", "-fy", device])
        mount.rmdir()
        if output.exists():
            shutil.rmtree(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/platform-backup.json")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create a new backup even when the previous one is recent",
    )
    args = parser.parse_args()
    path = Path(args.config)
    if os.geteuid() != 0 or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("Root-owned backup configuration required")
    cfg = json.loads(path.read_text())
    with Path("/run/lock/platform-backup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            previous = json.loads(Path(cfg["status_file"]).read_text())
            recent = (
                datetime.now(timezone.utc) - datetime.fromisoformat(previous["last_success_at"])
            ).total_seconds() < 20 * 3600
            if not args.force and previous["state"] == "ready" and recent:
                print("A verified backup is recent; next scheduled check will retry as needed")
                return
        except (OSError, ValueError, KeyError):
            pass

        def stop(signum, frame):
            raise RuntimeError("Backup interrupted")

        signal.signal(signal.SIGTERM, stop)
        try:
            backup(cfg)
        except Exception:
            status(
                cfg,
                state="failed",
                finished_at=now(),
                message="备份未完成，请检查挂载、快照空间及服务日志；已有有效备份继续保留。",
            )
            raise


if __name__ == "__main__":
    main()
