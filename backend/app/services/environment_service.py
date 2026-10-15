"""Small bundled examples and owned-instance checks, separate from routes."""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
from uuid import uuid4

from app.core.exceptions import ClusterOperationError
from app.core.workspace import PERSISTENT_PATH
from app.services.job_service import JobService
from app.services.storage_quota_service import StorageQuotaService
from app.services.storage_service import StorageService

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class EnvironmentService:
    @staticmethod
    async def check(db, user_id, container_id):
        allocation = JobService.allocation(db, user_id, container_id, running=True)
        try:
            output = await asyncio.to_thread(
                JobService.execute,
                allocation,
                (ASSETS / "environment_check.py").read_text(encoding="utf-8"),
            )
            # The Kubernetes SDK may turn a bare JSON response into a Python
            # repr when its exec endpoint declares a string response type.
            payload = next(
                line.removeprefix("PLATFORM_CHECK_RESULT=")
                for line in output.splitlines()
                if line.startswith("PLATFORM_CHECK_RESULT=")
            )
            result = json.loads(payload)
            if not isinstance(result.get("checks"), list):
                raise ValueError("Missing checks")
            return result
        except Exception as error:
            raise ClusterOperationError("环境检查未完成，请确认实例仍在运行后重试") from error

    @staticmethod
    def training_example(db, user_id):
        source = (ASSETS / "train.py").read_text(encoding="utf-8")
        StorageQuotaService.writable(db, user_id, len(source.encode()) + 4096)
        relative = f"training-{datetime.utcnow():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        with StorageQuotaService.write_guard():
            with StorageService._parent(user_id, relative) as (path, parent):
                os.mkdir(
                    path.name if parent is not None else path,
                    0o770,
                    **({"dir_fd": parent} if parent is not None else {}),
                )
            JobService.write(user_id, f"{relative}/train.py", source, exclusive=True)
        script = shlex.quote(f"{PERSISTENT_PATH}/{relative}/train.py")
        return {
            "folder": relative,
            "single_command": f"python {script}",
            "multi_command": f"torchrun --standalone --nproc_per_node=<申请的GPU数量> {script}",
        }
