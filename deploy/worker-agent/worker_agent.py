#!/usr/bin/env python3
"""受平台鉴权的 containerd 镜像保存代理；OCI 归档保存在共享个人镜像存储。"""

import concurrent.futures
import errno
import gzip
import hashlib
import hmac
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE = Path(os.environ.get("IMAGE_STORE_ROOT", "/mnt/platform-images"))
JOBS = Path(os.environ.get("WORKER_JOB_ROOT", str(STORE / ".jobs")))
SOCKET = os.environ.get("CONTAINERD_SOCKET", "/run/k3s/containerd/containerd.sock")
CONTENT = Path(
    os.environ.get(
        "CONTAINERD_CONTENT",
        "/var/lib/rancher/k3s/agent/containerd/io.containerd.content.v1.content/blobs/sha256",
    )
)
TOKEN = os.environ.get("WORKER_AGENT_TOKEN", "")
CTR = ["ctr", "--address", SOCKET, "--namespace", "k8s.io"]
CRI = ["crictl", "--runtime-endpoint", "unix://" + SOCKET]
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)
LOCK = threading.Lock()
SCHEDULED = set()


def run(args, timeout=120):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr.decode(errors="replace") or "运行时命令失败")[-1200:])
    return result.stdout


def save_job(job):
    path = JOBS / (job["job_id"] + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_job(job_id):
    return json.loads((JOBS / (job_id + ".json")).read_text(encoding="utf-8"))


def blob(digest):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("无效的镜像摘要")
    return CONTENT / digest.split(":")[1]


def image_manifest(image):
    rows = run(CTR + ["images", "list"]).decode().splitlines()
    digest = next(row.split()[2] for row in rows if row.split()[0] == image)
    manifest = json.loads(blob(digest).read_bytes())
    if "manifests" in manifest:
        descriptor = next(
            item
            for item in manifest["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        )
        manifest = json.loads(blob(descriptor["digest"]).read_bytes())
    return manifest


def encode(value):
    data = json.dumps(value, separators=(",", ":")).encode()
    return data, "sha256:" + hashlib.sha256(data).hexdigest()


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def snapshot(job):
    paused = None
    started = time.monotonic()
    temporary = None
    diff_path = None
    try:
        job.update(status="saving", started_at=time.time(), error=None)
        save_job(job)
        if shutil.disk_usage(STORE).free <= 0:
            raise RuntimeError("个人镜像存储空间不足，请清理后重试")
        containers = json.loads(run(CRI + ["ps", "--output", "json"]))["containers"]
        container = next(
            item
            for item in containers
            if item.get("labels", {}).get("io.kubernetes.pod.name") == job["pod_name"]
            and item.get("labels", {}).get("io.kubernetes.pod.namespace") == job["namespace"]
        )
        sandbox = json.loads(run(CRI + ["inspectp", container["podSandboxId"]]))["status"]
        labels = sandbox.get("labels", {})
        if labels.get("user-id") != str(job["user_id"]) or labels.get("allocation-id") != str(
            job["allocation_id"]
        ):
            raise RuntimeError("工作负载归属核对失败")
        info = json.loads(run(CTR + ["containers", "info", container["id"]]))
        base = image_manifest(info["Image"])
        config = json.loads(blob(base["config"]["digest"]).read_bytes())
        tasks = run(CTR + ["tasks", "list"]).decode().splitlines()
        if any(
            row.split()[0] == container["id"] and "PAUSED" in row for row in tasks if row.split()
        ):
            run(CTR + ["tasks", "resume", container["id"]])
        run(CTR + ["tasks", "pause", container["id"]])
        paused = container["id"]
        try:
            # ctr snapshots diff 将压缩层直接写到 stdout；大环境必须流式落盘，不能按文本或一次读入内存。
            diff_path = JOBS / (job["job_id"] + ".layer.gz")
            with diff_path.open("wb") as output:
                result = subprocess.run(
                    CTR
                    + [
                        "snapshots",
                        "--snapshotter",
                        info.get("Snapshotter", "overlayfs"),
                        "diff",
                        "--keep",
                        "--ref",
                        "platform-save-" + job["job_id"],
                        info["SnapshotKey"],
                    ],
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=900,
                )
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace")[-1200:])
        finally:
            run(CTR + ["tasks", "resume", paused])
            paused = None
        compressed = hashlib.sha256()
        with diff_path.open("rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                compressed.update(chunk)
        digest = "sha256:" + compressed.hexdigest()
        layer = diff_path
        required = int(
            (
                sum(blob(item["digest"]).stat().st_size for item in base["layers"])
                + layer.stat().st_size
            )
            * 1.02
        )
        if shutil.disk_usage(STORE).free < required:
            raise RuntimeError("个人镜像归档空间不足，请联系管理员清理后重试")
        uncompressed = hashlib.sha256()
        with gzip.open(layer, "rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                uncompressed.update(chunk)
                if time.monotonic() - started > 1200:
                    raise TimeoutError("保存镜像超时")
        config["rootfs"]["diff_ids"].append("sha256:" + uncompressed.hexdigest())
        config.setdefault("history", []).append(
            {"created_by": "campus-platform personal image save"}
        )
        # 只沿用基础镜像配置，不将实例令牌、SSH 密钥或临时环境变量写入镜像配置。
        config_data, config_digest = encode(config)
        layers = base["layers"] + [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": digest,
                "size": layer.stat().st_size,
            }
        ]
        manifest_data, manifest_digest = encode(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": config_digest,
                    "size": len(config_data),
                },
                "layers": layers,
            }
        )
        index = {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": manifest_digest,
                    "size": len(manifest_data),
                    "platform": {"os": "linux", "architecture": "amd64"},
                    "annotations": {
                        "org.opencontainers.image.ref.name": job["image_ref"],
                        "io.containerd.image.name": job["image_ref"],
                    },
                }
            ],
        }
        directory = STORE / ("user_" + str(job["user_id"]))
        directory.mkdir(exist_ok=True)
        destination = directory / (job["job_id"] + ".oci.tar")
        temporary = destination.with_suffix(".tmp")
        with tarfile.open(temporary, "w") as archive:
            add_bytes(archive, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
            add_bytes(archive, "index.json", encode(index)[0])
            add_bytes(archive, "blobs/sha256/" + config_digest.split(":")[1], config_data)
            add_bytes(archive, "blobs/sha256/" + manifest_digest.split(":")[1], manifest_data)
            for descriptor in {item["digest"]: item for item in layers}.values():
                archive.add(
                    layer if descriptor["digest"] == digest else blob(descriptor["digest"]),
                    arcname="blobs/sha256/" + descriptor["digest"].split(":")[1],
                    recursive=False,
                )
                if time.monotonic() - started > 1200:
                    raise TimeoutError("保存镜像超时")
        temporary.replace(destination)
        temporary = None
        run(
            CTR
            + [
                "images",
                "import",
                "--local",
                "--platform",
                "linux/amd64",
                str(destination),
            ],
            timeout=600,
        )
        job.update(
            status="ready",
            size_bytes=destination.stat().st_size,
            digest=manifest_digest,
            finished_at=time.time(),
        )
    except Exception as exc:
        logging.exception("Personal image save failed: job=%s", job["job_id"])
        message = (
            "个人存储额度或空间不足，请清理文件和镜像后重试"
            if isinstance(exc, OSError) and exc.errno in (errno.EDQUOT, errno.ENOSPC)
            else (str(exc) or type(exc).__name__)[:1200]
        )
        job.update(status="failed", error=message, finished_at=time.time())
    finally:
        if paused:
            try:
                run(CTR + ["tasks", "resume", paused])
            except Exception:
                job.update(status="failed", error="恢复实例运行失败，请联系管理员")
        if temporary:
            temporary.unlink(missing_ok=True)
        if diff_path:
            diff_path.unlink(missing_ok=True)
        save_job(job)
        with LOCK:
            SCHEDULED.discard(job["job_id"])


def schedule(job):
    with LOCK:
        if job["job_id"] not in SCHEDULED:
            SCHEDULED.add(job["job_id"])
            POOL.submit(snapshot, job)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return TOKEN and hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + TOKEN
        )

    def do_GET(self):
        if not self.authorized():
            return self.respond(403, {"error": "forbidden"})
        if self.path == "/health":
            return self.respond(200, {"status": "ready"})
        match = re.fullmatch(r"/snapshots/([0-9a-f-]{36})", self.path)
        if not match:
            return self.respond(404, {"error": "not found"})
        try:
            return self.respond(200, load_job(match[1]))
        except FileNotFoundError:
            return self.respond(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return self.respond(403, {"error": "forbidden"})
        if self.path != "/snapshots":
            return self.respond(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("invalid length")
            job = json.loads(self.rfile.read(length))
            assert re.fullmatch(r"[0-9a-f-]{36}", job["job_id"])
            assert isinstance(job["user_id"], int) and job["user_id"] > 0
            assert isinstance(job["allocation_id"], int) and job["allocation_id"] > 0
            assert re.fullmatch(
                r"pod-" + str(job["allocation_id"]) + r"-[a-z0-9-]+", job["pod_name"]
            )
            assert re.fullmatch(r"[a-z0-9-]+", job["namespace"])
            assert re.fullmatch(
                r"platform\.local/user-" + str(job["user_id"]) + r"/[a-z0-9._-]+:[A-Za-z0-9_.-]+",
                job["image_ref"],
            )
            try:
                existing = load_job(job["job_id"])
                for key in (
                    "user_id",
                    "allocation_id",
                    "pod_name",
                    "namespace",
                    "image_ref",
                ):
                    if existing[key] != job[key]:
                        return self.respond(409, {"error": "request conflict"})
                job = existing
            except FileNotFoundError:
                job.update(status="saving", created_at=time.time())
                save_job(job)
            if job["status"] == "saving":
                schedule(job)
            self.respond(200, job)
        except (ValueError, KeyError, AssertionError, TypeError):
            self.respond(422, {"error": "invalid job"})
        except Exception:
            self.respond(500, {"error": "worker agent unavailable"})

    def do_DELETE(self):
        if not self.authorized():
            return self.respond(403, {"error": "forbidden"})
        match = re.fullmatch(r"/snapshots/([0-9a-f-]{36})", self.path)
        if not match:
            return self.respond(404, {"error": "not found"})
        try:
            job = load_job(match[1])
            if job["status"] == "saving":
                return self.respond(409, {"error": "image still saving"})
            names = [
                row.split()[0]
                for row in run(CTR + ["images", "list"]).decode().splitlines()
                if row.split()
            ]
            if job["image_ref"] in names:
                run(CTR + ["images", "remove", job["image_ref"]])
            (STORE / ("user_" + str(job["user_id"])) / (job["job_id"] + ".oci.tar")).unlink(
                missing_ok=True
            )
            job.update(status="deleted", finished_at=time.time())
            save_job(job)
            self.respond(200, job)
        except FileNotFoundError:
            self.respond(404, {"error": "not found"})
        except Exception:
            self.respond(500, {"error": "worker agent unavailable"})


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("WORKER_AGENT_TOKEN is required")
    JOBS.mkdir(parents=True, exist_ok=True)
    for path in JOBS.glob("*.json"):
        job = json.loads(path.read_text())
        if job["status"] == "saving":
            schedule(job)
    ThreadingHTTPServer(
        (os.environ.get("WORKER_AGENT_BIND", "REPLACE_NODE_INTERNAL_IP"), 8091), Handler
    ).serve_forever()
