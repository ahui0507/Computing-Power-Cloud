#!/usr/bin/env python3
"""Linux 主机采集服务，仅用标准库；不读取账户、用户文件或进程命令。"""
import csv
import io
import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("platform-monitor")


def cpu_counters(text):
    values = [int(value) for value in text.splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def cpu_percent(previous, current):
    if previous is None or current[0] <= previous[0]:
        return None
    total, idle = current[0] - previous[0], current[1] - previous[1]
    return round(min(100.0, max(0.0, 100 * (total - idle) / total)), 2)


def numeric(value):
    try:
        result = float(value.strip())
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def parse_gpus(text):
    values = []
    for row in csv.reader(io.StringIO(text), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 8:
            raise ValueError("GPU 采集字段数量错误")
        index, uuid, name, utilization, used, total, temperature, power = row
        values.append({"index": int(index), "uuid": uuid, "name": name,
            "utilization": numeric(utilization), "memory_used_mb": numeric(used),
            "memory_total_mb": numeric(total), "temperature": numeric(temperature), "power_watts": numeric(power)})
    return values


def gpu_sample():
    try:
        result = subprocess.run(["nvidia-smi",
            "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8)
        if result.returncode:
            if "No devices were found" in result.stdout + result.stderr:
                return [], None
            return [], "NVIDIA 指标暂时不可读取"
        return parse_gpus(result.stdout), None
    except FileNotFoundError:
        return [], None  # 无 GPU 的节点由服务器登记数量决定是否需要 GPU 指标。
    except (subprocess.TimeoutExpired, ValueError):
        return [], "GPU 采集超时或响应异常"


@lru_cache(maxsize=1)
def driver_capabilities():
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=8)
        driver = re.search(r"Driver Version:\s*([0-9.]+)", result.stdout)
        cuda = re.search(r"CUDA Version:\s*([0-9.]+)", result.stdout)
        return {"driver_version": driver[1] if driver else None, "driver_cuda_max": cuda[1] if cuda else None}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"driver_version": None, "driver_cuda_max": None}


def parse_device_allocations(text):
    checkpoint = json.loads(text)
    data = checkpoint["Data"]
    if isinstance(data, str):
        data = json.loads(data)
    entries = data["PodDeviceEntries"] or []
    mapping = {}
    for entry in entries:
        if entry.get("ResourceName") != "nvidia.com/gpu":
            continue
        devices = entry.get("DeviceIDs", [])
        if isinstance(devices, dict):
            devices = [device for group in devices.values() for device in group]
        for device in devices:
            mapping.setdefault(device, []).append(entry["PodUID"])
    return mapping


def sample(previous=None, node_name=None):
    current = cpu_counters(Path("/proc/stat").read_text())
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        memory[name] = int(value.strip().split()[0])
    total, available = memory["MemTotal"], memory["MemAvailable"]
    gpus, gpu_error = gpu_sample()
    mapping_available = False
    try:
        mapping = parse_device_allocations(Path("/var/lib/kubelet/device-plugins/kubelet_internal_checkpoint").read_text())
        mapping_available = True
    except (OSError, ValueError, KeyError, TypeError):
        mapping = {}
    for gpu in gpus:
        gpu["pod_uids"] = mapping.get(gpu["uuid"], [])
    return {"node_name": node_name or socket.gethostname(), "collected_at": datetime.now(timezone.utc).isoformat(),
        "cpu_usage": cpu_percent(previous, current), "mem_usage": round((total - available) / total * 100, 2),
        "cpu_cores": os.cpu_count() or 1, "memory_total_mb": round(total / 1024, 2),
        "memory_used_mb": round((total - available) / 1024, 2), "gpus": gpus, "gpu_error": gpu_error,
        "device_mapping_available": mapping_available, **driver_capabilities()}, current


def run():
    url = os.environ["PLATFORM_MONITOR_URL"]
    token = os.environ["PLATFORM_MONITOR_TOKEN"]
    node_name = os.environ.get("PLATFORM_MONITOR_NODE", socket.gethostname())
    interval = max(5, int(os.environ.get("PLATFORM_MONITOR_INTERVAL", "15")))
    previous = cpu_counters(Path("/proc/stat").read_text())
    time.sleep(1)
    while True:
        started = time.monotonic()
        try:
            payload, previous = sample(previous, node_name)
            request = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read(4096)
        except urllib.error.HTTPError as error:
            logger.warning("指标上报被拒绝：HTTP %s", error.code)
        except Exception as error:
            # 不记录 URL、令牌、环境变量或响应正文。
            logger.warning("指标采集或上报暂不可用：%s", type(error).__name__)
        time.sleep(max(1, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
