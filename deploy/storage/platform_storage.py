#!/usr/bin/env python3
"""Root helper for one configured data filesystem; no caller-supplied paths."""

import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import stat
import struct
import sys

CONFIG = Path("/etc/platform-storage.json")
PROJECT_BASE = 100000
FSGETXATTR, FSSETXATTR = 0x801C581F, 0x401C5820
PROJECT_INHERIT = 0x200


class QuotaCapacityError(ValueError):
    """A rejected allocation leaves existing limits and data intact."""


class DiskQuota(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "hard_blocks",
            "soft_blocks",
            "space",
            "hard_inodes",
            "soft_inodes",
            "inodes",
            "block_time",
            "inode_time",
        )
    ]
    _fields_.append(("valid", ctypes.c_uint32))


def quota_call(device, project_id, operation, values=None, kind=2):
    values = values or DiskQuota()
    library = ctypes.CDLL(None, use_errno=True)
    library.quotactl.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    command = (operation << 8) | kind
    if library.quotactl(
        ctypes.c_int(command), os.fsencode(device), project_id, ctypes.byref(values)
    ):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return values


def config():
    info = CONFIG.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("Storage configuration must be root-owned and not writable by other users")
    value = json.loads(CONFIG.read_text())
    mount = Path(value["data_mount"]).resolve()
    if mount == Path("/") or not mount.is_mount():
        raise ValueError("Dedicated data volume is not mounted")
    for key in ("workspace_root", "image_root"):
        root = Path(value[key])
        if not root.is_absolute() or root.is_symlink() or root.stat().st_dev != mount.stat().st_dev:
            raise ValueError("Storage roots must be on the configured data filesystem")
    return value


def volume_status(cfg):
    usage = os.statvfs(cfg["data_mount"])
    total = usage.f_blocks * usage.f_frsize
    return {
        "total_bytes": total,
        "available_bytes": max(0, usage.f_bavail * usage.f_frsize - cfg.get("reserve_free_bytes", 0)),
        "user_capacity_bytes": cfg.get("pool_capacity_bytes", int(total * (100 - cfg.get("reserve_percent", 20)) / 100)),
        "inode_capacity": usage.f_files,
        "used_percent": (1 - usage.f_bfree / usage.f_blocks) * 100 if usage.f_blocks else 0,
    }


def assign_project(path, project_id):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        attributes = bytearray(28)
        fcntl.ioctl(descriptor, FSGETXATTR, attributes, True)
        fields = list(struct.unpack("=IIIII8s", attributes))
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if fields[3] == project_id and (not directory or fields[0] & PROJECT_INHERIT):
            return False
        fields[3] = project_id
        if directory:
            fields[0] |= PROJECT_INHERIT
        fcntl.ioctl(descriptor, FSSETXATTR, struct.pack("=IIIII8s", *fields))
        return True
    finally:
        os.close(descriptor)


def prepare_roots(cfg, user_id):
    project_id = PROJECT_BASE + user_id
    for key in ("workspace_root", "image_root"):
        root = Path(cfg[key]) / f"user_{user_id}"
        if root.is_symlink():
            raise ValueError("User storage cannot be a symlink")
        root.mkdir(mode=0o2770, exist_ok=True)
        os.chown(root, cfg["storage_uid"], cfg["storage_gid"])
        root.chmod(0o2770)
        if assign_project(root, project_id):
            for directory, dirs, files in os.walk(root, followlinks=False):
                for name in dirs + files:
                    child = Path(directory) / name
                    if not child.is_symlink():
                        assign_project(child, project_id)
    return project_id


def status(cfg, user_id):
    project_id = PROJECT_BASE + user_id
    value = quota_call(cfg["device"], project_id, 0x800007)
    capacity = value.hard_blocks * 1024
    volume = volume_status(cfg)
    shared = quota_call(cfg["device"], cfg["storage_uid"], 0x800007, kind=0)
    volume["available_bytes"] = min(
        volume["available_bytes"], max(0, shared.hard_blocks * 1024 - shared.space)
    )
    return {
        "user_id": user_id,
        "used_bytes": value.space,
        "limit_bytes": capacity,
        "used_percent": value.space / capacity * 100 if capacity else None,
        "used_inodes": value.inodes,
        "inode_limit": value.hard_inodes,
        "enforcement": "filesystem",
        "volume": volume,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ensure", "status", "health"))
    parser.add_argument("user_id", nargs="?", type=int)
    parser.add_argument("--share-percent", type=float)
    parser.add_argument("--limit-bytes", type=int)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Storage helper requires root")
    cfg = config()
    if args.action == "health":
        quota_call(cfg["device"], PROJECT_BASE, 0x800007)
        shared = quota_call(cfg["device"], cfg["storage_uid"], 0x800007, kind=0)
        if not shared.hard_blocks or not shared.hard_inodes:
            raise ValueError("Global storage quota has not been initialized")
        print(json.dumps({"enforcement": "filesystem", "volume": volume_status(cfg)}))
        return
    if args.user_id is None or not 0 < args.user_id < 1000000000:
        raise ValueError("Invalid user ID")
    lock_path = Path(cfg["data_mount"]) / ".platform-quota.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "ensure":
            if args.limit_bytes is None and (args.share_percent is None or not 0 < args.share_percent <= 100):
                raise ValueError("Storage share must be within (0, 100]")
            volume = volume_status(cfg)
            limit = args.limit_bytes if args.limit_bytes is not None else int(volume["user_capacity_bytes"] * args.share_percent / 100)
            if not isinstance(limit, int) or limit < 1024:
                raise ValueError("Storage limit must be positive")
            ledger_path = Path(cfg["data_mount"]) / ".platform-quota-ledger.json"
            if ledger_path.is_symlink():
                raise ValueError("Quota ledger cannot be a symlink")
            ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
            prior = ledger.get(str(args.user_id), 0)
            committed = sum(int(v) for k,v in ledger.items() if k != str(args.user_id))
            project_id = PROJECT_BASE + args.user_id
            current = quota_call(cfg["device"], project_id, 0x800007)
            shared_current = quota_call(cfg["device"], cfg["storage_uid"], 0x800007, kind=0)
            if committed + limit > volume["user_capacity_bytes"] or limit < current.space:
                raise QuotaCapacityError("Insufficient pool capacity or requested limit below current usage")
            if limit > prior and limit - prior > volume["available_bytes"]:
                raise QuotaCapacityError("Insufficient physical free space above reserve")
            if committed + limit < shared_current.space:
                raise QuotaCapacityError("Pool commitments cannot be lower than existing platform data")
            project_id = prepare_roots(cfg, args.user_id)
            shared = DiskQuota()
            shared.hard_blocks = shared.soft_blocks = volume["user_capacity_bytes"] // 1024
            shared.hard_inodes = shared.soft_inodes = cfg.get("pool_inode_capacity", int(volume["inode_capacity"] * (100 - cfg.get("reserve_percent", 20)) / 100))
            shared.valid = 1 | 4
            quota_call(cfg["device"], cfg["storage_uid"], 0x800008, shared, kind=0)
            quota = DiskQuota()
            quota.hard_blocks = quota.soft_blocks = max(
                1, limit // 1024
            )
            quota.hard_inodes = quota.soft_inodes = max(
                1, min(cfg.get("default_user_inode_limit", 200000), int(shared.hard_inodes * limit / volume["user_capacity_bytes"]))
            )
            quota.valid = 1 | 4  # Only change limits, preserve current usage.
            quota_call(cfg["device"], project_id, 0x800008, quota)
            ledger[str(args.user_id)] = limit
            temporary = ledger_path.with_suffix(".tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(ledger, stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, ledger_path)
        print(json.dumps(status(cfg, args.user_id)))


if __name__ == "__main__":
    try:
        main()
    except QuotaCapacityError as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(3)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(1)
