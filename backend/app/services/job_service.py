"""在所属实例中运行后台命令，元数据与日志保存于用户持久工作目录。"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from kubernetes.stream import stream
from app.core.config import settings
from app.core.time import utc_iso
from app.core.workspace import persistent_path
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError, ClusterOperationError
from app.infrastructure.kubernetes.client import create_clients
from app.models import Allocation, AllocationStatus
from app.services.access_service import AccessService
from app.services.storage_service import StorageService


RUNNER = """import json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).parent
def save(name,data):
    temporary=root/(name+".tmp")
    temporary.write_text(json.dumps(data))
    temporary.replace(root/name)
save("pid.json",{"pid":os.getpid(),"started_at":datetime.now(timezone.utc).isoformat()})
try:
    meta=json.loads((root/"metadata.json").read_text())
    with (root/"output.log").open("ab",buffering=0) as output:
        result=subprocess.run(meta["command"],shell=True,executable="/bin/bash",cwd="/workspace",stdout=output,stderr=subprocess.STDOUT)
    save("result.json",{"exit_code":result.returncode,"finished_at":datetime.now(timezone.utc).isoformat()})
except Exception as exc:
    save("result.json",{"exit_code":1,"finished_at":datetime.now(timezone.utc).isoformat(),"error":str(exc)})
"""


class JobService:
    @staticmethod
    def relative(job_id, filename):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ResourceNotFoundError("任务")
        return f".cloud-jobs/{job_id}/{filename}"

    @staticmethod
    def read(user_id, relative, *, tail=False):
        try:
            with StorageService._parent(user_id, relative) as (path, parent):
                fd = os.open(
                    path.name if parent is not None else path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    **({"dir_fd": parent} if parent is not None else {}),
                )
                with os.fdopen(fd, "rb") as handle:
                    if tail:
                        handle.seek(max(0, os.fstat(handle.fileno()).st_size - 128 * 1024))
                    return handle.read(128 * 1024).decode("utf-8", errors="replace")
        except (ResourceNotFoundError, FileNotFoundError):
            return None

    @staticmethod
    def write(user_id, relative, text, *, exclusive=False):
        with StorageService._parent(user_id, relative) as (path, parent):
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | (os.O_EXCL if exclusive else os.O_TRUNC)
            )
            fd = os.open(
                path.name if parent is not None else path,
                flags,
                0o660,
                **({"dir_fd": parent} if parent is not None else {}),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)

    @staticmethod
    def execute(allocation, command):
        core, network = create_clients()
        namespace = AccessService.allocation_options(allocation).get(
            "namespace", settings.K8S_NAMESPACE
        )
        try:
            pod = core.read_namespaced_pod(allocation.pod_name, namespace)
            labels = pod.metadata.labels or {}
            if labels.get("user-id") != str(allocation.user_id) or labels.get(
                "allocation-id"
            ) != str(allocation.id):
                raise ResourceConflictError("实例归属核对失败")
            return stream(
                core.connect_get_namespaced_pod_exec,
                allocation.pod_name,
                namespace,
                command=["python", "-c", command],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _request_timeout=15,
            )
        finally:
            core.api_client.close()
            if network.api_client is not core.api_client:
                network.api_client.close()

    @staticmethod
    def allocation(db, user_id, container_id, *, running=False):
        allocation = (
            db.query(Allocation).filter_by(user_id=user_id, container_id=container_id).first()
        )
        if not allocation:
            raise ResourceNotFoundError("实例")
        if running and allocation.status != AllocationStatus.ACTIVE:
            raise ResourceConflictError("请先选择运行中的实例")
        return allocation

    @staticmethod
    def get(db, user_id, job_id):
        text = JobService.read(user_id, JobService.relative(job_id, "metadata.json"))
        if not text:
            raise ResourceNotFoundError("任务")
        try:
            meta = json.loads(text)
            allocation = JobService.allocation(db, user_id, meta["container_id"])
            result = json.loads(
                JobService.read(user_id, JobService.relative(job_id, "result.json")) or "null"
            )
            cancelled = JobService.read(user_id, JobService.relative(job_id, "cancelled.json"))
            pid = json.loads(
                JobService.read(user_id, JobService.relative(job_id, "pid.json")) or "null"
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ResourceConflictError("任务记录损坏") from exc
        finished = result.get("finished_at") if result else None
        if cancelled:
            status, finished = "cancelled", json.loads(cancelled)["finished_at"]
        elif result:
            status = "completed" if result.get("exit_code") == 0 else "failed"
        elif allocation.status not in (AllocationStatus.ACTIVE, AllocationStatus.APPROVED):
            status, finished = "interrupted", utc_iso(allocation.end_time)
        else:
            status = "running" if pid else "pending"
        return {
            "job_id": job_id,
            "container_id": allocation.container_id,
            "name": meta.get("name", job_id),
            "instance_name": allocation.instance.instance_name
            if allocation.instance
            else "算力实例",
            "command": meta.get("command", ""),
            "status": status,
            "created_at": meta.get("created_at"),
            "started_at": pid.get("started_at") if pid else None,
            "finished_at": finished,
            "exit_code": result.get("exit_code") if result else None,
        }

    @staticmethod
    def list(db, user_id):
        root = StorageService.resolve_path(user_id, ".cloud-jobs")
        if not root.exists():
            return []
        rows = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name)[:1000]:
            if not directory.is_symlink() and re.fullmatch(r"[a-f0-9]{32}", directory.name):
                try:
                    rows.append(JobService.get(db, user_id, directory.name))
                except (ResourceNotFoundError, ResourceConflictError, ValueError):
                    continue
        return sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)

    @staticmethod
    async def submit(db, user_id, body):
        allocation = JobService.allocation(db, user_id, body.container_id, running=True)
        relative = JobService.relative(body.job_id, "metadata.json")
        directory = StorageService.resolve_path(user_id, str(PurePosixPath(relative).parent))
        directory.mkdir(mode=0o770, parents=True, exist_ok=True)
        metadata = {
            "name": body.name.strip(),
            "command": body.command,
            "container_id": body.container_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            JobService.write(user_id, relative, json.dumps(metadata), exclusive=True)
        except FileExistsError:
            previous = JobService.get(db, user_id, body.job_id)
            if (previous["command"], previous["container_id"]) != (body.command, body.container_id):
                raise ResourceConflictError("重试标识对应的任务参数已改变")
            return previous
        JobService.write(user_id, JobService.relative(body.job_id, "runner.py"), RUNNER)
        runner = (
            persistent_path(AccessService.allocation_options(allocation))
            + "/"
            + JobService.relative(body.job_id, "runner.py")
        )
        command = (
            "import subprocess,sys; subprocess.Popen([sys.executable,"
            + repr(runner)
            + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); print('started')"
        )
        try:
            output = await asyncio.to_thread(JobService.execute, allocation, command)
            if "started" not in output:
                raise ClusterOperationError("任务启动结果未确认，请刷新任务列表后重试")
        except Exception as exc:
            # 保留原标识，网络结果不确定时不能再次启动同一命令。
            raise ClusterOperationError("任务启动结果未确认，请刷新列表检查原任务") from exc
        return JobService.get(db, user_id, body.job_id)

    @staticmethod
    async def cancel(db, user_id, job_id):
        job = JobService.get(db, user_id, job_id)
        if job["status"] not in ("pending", "running"):
            return job
        allocation = JobService.allocation(db, user_id, job["container_id"], running=True)
        root = persistent_path(AccessService.allocation_options(allocation))
        runner = root + "/" + JobService.relative(job_id, "runner.py")
        pid_path = root + "/" + JobService.relative(job_id, "pid.json")
        command = (
            "import json,os,signal; from pathlib import Path; p=Path(" + repr(pid_path) + "); "
            "pid=json.loads(p.read_text())['pid'] if p.exists() else 0; "
            "cmd=Path('/proc/'+str(pid)+'/cmdline'); "
            "alive=pid>1 and cmd.exists() and " + repr(runner.encode()) + " in cmd.read_bytes(); "
            "os.killpg(pid,signal.SIGTERM) if alive else None; print('cancelled' if alive else 'not-running')"
        )
        output = await asyncio.to_thread(JobService.execute, allocation, command)
        if "cancelled" not in output:
            raise ResourceConflictError("任务尚未启动或已经结束，请刷新后重试")
        JobService.write(
            user_id,
            JobService.relative(job_id, "cancelled.json"),
            json.dumps({"finished_at": datetime.now(timezone.utc).isoformat()}),
        )
        return JobService.get(db, user_id, job_id)
