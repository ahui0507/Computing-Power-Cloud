"""Independent, read-only node monitor; run outside the tested GPU container."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


FIELDS = ["index", "uuid", "temperature.gpu", "utilization.gpu", "power.draw",
          "power.limit", "clocks.current.sm", "memory.used",
          "ecc.errors.uncorrected.volatile.total", "ecc.errors.corrected.volatile.total"]
ERROR = re.compile(r"NVRM:.*(?:Xid|fallen off|RmInitAdapter)|AER:.*(?:Fatal|Uncorrected)|"
                   r"(?:IOMMU|DMAR).*(?:fault|error)", re.IGNORECASE)


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=8, check=True)
    return result.stdout


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uuid", action="append", required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output
    journal = run(["journalctl", "-k", "-n", "1", "--show-cursor", "--no-pager"])
    cursor = re.search(r"-- cursor: (.+)", journal).group(1)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    module = Path("/sys/module/nvidia/version").read_text().strip()
    (output / "before.xml").write_text(run(["nvidia-smi", "-q", "-x"]))
    initial = None
    history = []
    errors = []
    fault = None
    started = time.monotonic()
    last_journal = 0
    with (output / "telemetry.jsonl").open("w", buffering=1) as log:
        try:
            while time.monotonic() - started < args.seconds:
                text = run(["nvidia-smi", "--query-gpu=" + ",".join(FIELDS),
                            "--format=csv,noheader,nounits"])
                inventory = [dict(zip(FIELDS, [item.strip() for item in row]))
                             for row in csv.reader(text.splitlines())]
                selected = [row for row in inventory if row["uuid"] in args.uuid]
                if len(selected) != len(args.uuid):
                    raise RuntimeError("A tested GPU disappeared from NVML inventory")
                if initial is None:
                    initial = {row["uuid"]: row for row in selected}
                if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot:
                    raise RuntimeError("Compute node reboot detected")
                if Path("/sys/module/nvidia/version").read_text().strip() != module:
                    raise RuntimeError("NVIDIA module version changed")
                record = {"utc": datetime.now(timezone.utc).isoformat(),
                          "elapsed_seconds": time.monotonic() - started,
                          "physical_gpu_count": len(inventory), "gpus": selected}
                history.append(record)
                log.write(json.dumps(record) + "\n")
                for row in selected:
                    if float(row["temperature.gpu"]) >= 88:
                        raise RuntimeError("Temperature reached stop threshold 88 C: " + row["uuid"])
                    field = "ecc.errors.uncorrected.volatile.total"
                    if row[field].isdigit() and initial[row["uuid"]][field].isdigit():
                        if int(row[field]) > int(initial[row["uuid"]][field]):
                            raise RuntimeError("New uncorrectable ECC error: " + row["uuid"])
                if time.monotonic() - last_journal >= 5:
                    journal = run(["journalctl", "-k", "--after-cursor=" + cursor,
                                   "--show-cursor", "--no-pager"])
                    match = re.search(r"-- cursor: (.+)", journal)
                    if match:
                        cursor = match.group(1)
                    new_errors = [line for line in journal.splitlines() if ERROR.search(line)]
                    errors.extend(new_errors)
                    (output / "kernel-errors.log").write_text("\n".join(errors), encoding="utf-8")
                    last_journal = time.monotonic()
                    if new_errors:
                        raise RuntimeError("New kernel GPU/PCIe/IOMMU error; inspect kernel-errors.log")
                save(output / "live.json", record)
                if (output / "stop").exists():
                    break
                time.sleep(1)
        except BaseException as error:
            fault = {"error_type": type(error).__name__, "error": str(error),
                     "utc": datetime.now(timezone.utc).isoformat()}
            save(output / "fault.json", fault)
        finally:
            try:
                (output / "after.xml").write_text(run(["nvidia-smi", "-q", "-x"]))
            except Exception as error:
                fault = fault or {"error": str(error)}
            summary = {"passed": fault is None, "fault": fault,
                       "duration_seconds": time.monotonic() - started,
                       "boot_id": boot, "driver_module_version": module,
                       "kernel_errors": errors, "samples": len(history), "gpus": {}}
            for uuid in args.uuid:
                rows = [gpu for item in history for gpu in item["gpus"] if gpu["uuid"] == uuid]
                if rows:
                    summary["gpus"][uuid] = {
                        "max_temperature_c": max(float(row["temperature.gpu"]) for row in rows),
                        "max_utilization_percent": max(float(row["utilization.gpu"]) for row in rows),
                        "max_power_w": max(float(row["power.draw"]) for row in rows),
                        "max_memory_mib": max(float(row["memory.used"]) for row in rows),
                        "max_sm_clock_mhz": max(float(row["clocks.current.sm"]) for row in rows),
                        "first": rows[0], "last": rows[-1],
                    }
            save(output / "summary.json", summary)


if __name__ == "__main__":
    main()
