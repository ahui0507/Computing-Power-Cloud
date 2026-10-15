#!/usr/bin/env python3
"""Prepare dedicated data volumes from verified, unused LVM extents."""

import argparse
import json
import os
from pathlib import Path
import subprocess


def run(*command, capture=False, allowed=(0,)):
    result = subprocess.run(command, text=True, capture_output=capture)
    if result.returncode not in allowed:
        raise RuntimeError("Command failed: " + command[0])
    return result.stdout.strip() if capture else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("control", "worker"))
    args = parser.parse_args()
    assert os.geteuid() == 0
    mount = Path("/var/lib/images" if args.role == "control" else "/var/lib/platform-data")
    device = "/dev/ubuntu-vg/" + ("images" if args.role == "control" else "platform-data")
    plan_file = Path("/var/lib/platform-storage-" + args.role + "-plan.json")
    if plan_file.exists():
        plan = json.loads(plan_file.read_text())
        assert plan["device"] == device
    else:
        vg = json.loads(
            run(
                "vgs",
                "--reportformat",
                "json",
                "--units",
                "b",
                "--nosuffix",
                "-o",
                "vg_name,vg_free_count,vg_extent_size",
                "ubuntu-vg",
                capture=True,
            )
        )["report"][0]["vg"][0]
        extents = int(vg["vg_free_count"]) * 80 // 100
        assert extents > 0
        if args.role == "control":
            assert os.path.realpath(
                run(
                    "findmnt",
                    "-n",
                    "-o",
                    "SOURCE",
                    "--target",
                    str(mount),
                    capture=True,
                )
            ) == os.path.realpath(device)
            for directory, dirs, files in os.walk(mount):
                assert not any((Path(directory) / name).stat().st_size for name in files), (
                    "Existing data volume is not empty"
                )
            size = float(
                run(
                    "lvs",
                    "--noheadings",
                    "--units",
                    "b",
                    "--nosuffix",
                    "-o",
                    "lv_size",
                    device,
                    capture=True,
                )
            )
            extents += int(size / float(vg["vg_extent_size"]))
        else:
            assert not Path(device).exists(), "Refusing to format an existing volume"
        plan = {
            "device": device,
            "target_extents": extents,
            "role": args.role,
            "new_volume": args.role == "worker",
        }
        plan_file.write_text(json.dumps(plan, indent=2) + "\n")
        plan_file.chmod(0o600)
    if (mount / ".platform-storage-ready").exists():
        print("Dedicated volume already prepared:", mount)
        return
    if args.role == "control":
        if mount.is_mount():
            run("umount", str(mount))
        current = int(
            float(
                run(
                    "lvs",
                    "--noheadings",
                    "--units",
                    "b",
                    "--nosuffix",
                    "-o",
                    "lv_size",
                    device,
                    capture=True,
                )
            )
        )
        extent = int(
            float(
                run(
                    "vgs",
                    "--noheadings",
                    "--units",
                    "b",
                    "--nosuffix",
                    "-o",
                    "vg_extent_size",
                    "ubuntu-vg",
                    capture=True,
                )
            )
        )
        if current < plan["target_extents"] * extent:
            run("lvextend", "-l", str(plan["target_extents"]), device)
        run("e2fsck", "-fy", device, allowed=(0, 1))
        run("resize2fs", device)
        run(
            "tune2fs",
            "-O",
            "project,quota",
            "-Q",
            "usrquota,prjquota",
            "-m",
            "20",
            "-L",
            "platform-data",
            device,
        )
        run("e2fsck", "-fy", device, allowed=(0, 1))
        options = "defaults,usrquota,prjquota"
    else:
        if not Path(device).exists():
            run(
                "lvcreate",
                "-l",
                str(plan["target_extents"]),
                "-n",
                "platform-data",
                "ubuntu-vg",
            )
        if not run("blkid", "-s", "TYPE", "-o", "value", device, capture=True, allowed=(0, 2)):
            run("mkfs.ext4", "-m", "20", "-L", "platform-worker-data", device)
        options = "defaults"
    mount.mkdir(parents=True, exist_ok=True)
    fstab = Path("/etc/fstab")
    backup = Path("/etc/fstab.before-platform-storage")
    if not backup.exists():
        backup.write_bytes(fstab.read_bytes())
    lines = [
        line
        for line in fstab.read_text().splitlines()
        if not (
            line
            and not line.startswith("#")
            and len(line.split()) > 1
            and line.split()[1] == str(mount)
        )
    ]
    lines.append(f"{device} {mount} ext4 {options} 0 2")
    fstab.write_text("\n".join(lines) + "\n")
    run("mount", str(mount))
    (mount / ".platform-storage-ready").write_text(json.dumps(plan) + "\n")
    print("Prepared dedicated volume:", mount)


if __name__ == "__main__":
    main()
