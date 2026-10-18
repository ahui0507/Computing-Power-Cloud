"""Authenticated SSH transport over the existing website WebSocket entry."""
import asyncio
from contextlib import suppress
from pathlib import Path
import json

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.response import success_response
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.models import User
from app.services.access_service import AccessService
from app.services.job_service import JobService

router = APIRouter(prefix="/resource", tags=["实例 SSH"])


def ssh_destination(db, user_id, container_id):
    allocation = JobService.allocation(db, user_id, container_id, running=True)
    options = AccessService.allocation_options(allocation)
    if not options.get("ssh_enabled") or not allocation.ssh_port:
        raise ValueError("SSH is unavailable")
    core, network = create_clients()
    try:
        pod = core.read_namespaced_pod(allocation.pod_name, options.get("namespace", "default"))
        KubernetesGateway._check_owner(pod, allocation.id, user_id)
        if pod.status.phase != "Running" or not pod.status.pod_ip:
            raise ValueError("Instance is not running")
        return pod.status.pod_ip, 22
    finally:
        core.api_client.close()
        if network.api_client is not core.api_client:
            network.api_client.close()


@router.get("/{container_id}/ssh-tool")
def download_tool(
    container_id: str, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    JobService.allocation(db, user.id, container_id, running=True)
    source = (Path(__file__).resolve().parents[1] / "assets/ssh_tunnel.py").read_text(encoding="utf-8")
    source = source.replace('DEFAULT_URL = ""', "DEFAULT_URL = " + json.dumps(str(request.base_url).rstrip("/")))
    source = source.replace('DEFAULT_INSTANCE = ""', "DEFAULT_INSTANCE = " + json.dumps(container_id))
    return success_response(data={"filename": "platform-ssh.py", "content": source})


@router.websocket("/{container_id}/ssh-tunnel")
async def tunnel(websocket: WebSocket, container_id: str, db: Session = Depends(get_db)):
    reader = writer = None
    tasks = []
    try:
        scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            await websocket.close(code=1008)
            return
        user = await get_current_user(
            websocket, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db,
        )
        # The client never chooses an IP or port; ownership is checked against the Pod.
        destination = ssh_destination(db, user.id, container_id)
        db.close()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(*destination), timeout=10)
        await websocket.accept()

        async def receive():
            while True:
                data = await websocket.receive_bytes()
                if len(data) > 1024 * 1024:
                    raise ValueError("Oversized frame")
                writer.write(data)
                await writer.drain()

        async def send():
            while data := await reader.read(65536):
                await websocket.send_bytes(data)

        tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except Exception:
        # Do not log headers, tokens or transport contents.
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if writer:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
        with suppress(Exception):
            await websocket.close()
