import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.main import app
from app.models import Allocation, AllocationStatus, UserStatus
from app.models.operation import AllocationOperation, OperationKind
from app.routers import ssh_tunnel


@pytest.fixture
def setup(db, monkeypatch):
    row = Allocation(request_id="tunnel-test", user_id=1, node_id=1, pool_id=1, image_id=1,
                     requested_gpu_count=1, gpu_type_id=1, status=AllocationStatus.ACTIVE,
                     container_id="tunnel-owned", pod_name="pod-owned", ssh_port=31022)
    db.add(row)
    db.flush()
    db.add(AllocationOperation(allocation_id=row.id, kind=OperationKind.CREATE,
        payload={"options": {"namespace": "default", "ssh_enabled": True}}))
    db.commit()
    core, network = MagicMock(), MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels={"allocation-id": str(row.id), "user-id": "1"}),
        status=SimpleNamespace(phase="Running", pod_ip="192.0.2.55"),
    )
    monkeypatch.setattr(ssh_tunnel, "create_clients", lambda: (core, network))
    destinations = []

    async def connect(host, port):
        destinations.append((host, port))
        queue = asyncio.Queue()
        queue.put_nowait(b"SSH-2.0-test\r\n")

        class Reader:
            async def read(self, size):
                return await queue.get()

        class Writer:
            def write(self, data):
                queue.put_nowait(data)
            async def drain(self):
                pass
            def close(self):
                pass
            async def wait_closed(self):
                pass

        return Reader(), Writer()

    monkeypatch.setattr(ssh_tunnel.asyncio, "open_connection", connect)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, row, core, destinations
    app.dependency_overrides.clear()


def auth(user_id=1):
    return {"Authorization": "Bearer " + create_access_token({"sub": str(user_id)})}


def test_tunnel_relays_binary_to_only_the_owned_pod(setup):
    client, row, core, destinations = setup
    with client.websocket_connect(f"/resource/{row.container_id}/ssh-tunnel", headers=auth()) as websocket:
        assert websocket.receive_bytes() == b"SSH-2.0-test\r\n"
        payload = bytes(range(256)) * 200
        websocket.send_bytes(payload)
        assert websocket.receive_bytes() == payload
    assert destinations == [("192.0.2.55", 22)]
    core.api_client.close.assert_called()


@pytest.mark.parametrize("kind", ["anonymous", "other-user", "expired", "refresh", "disabled", "stopped", "wrong-pod"])
def test_tunnel_rejects_invalid_access_before_opening_tcp(setup, db, kind):
    from app.models import User
    client, row, core, destinations = setup
    headers = auth()
    if kind == "anonymous":
        headers = {}
    elif kind == "other-user":
        headers = auth(2)
    elif kind == "expired":
        headers = {"Authorization": "Bearer " + create_access_token({"sub": "1"}, timedelta(seconds=-1))}
    elif kind == "refresh":
        headers = {"Authorization": "Bearer " + create_refresh_token({"sub": "1"})}
    elif kind == "disabled":
        db.get(User, 1).status = UserStatus.DISABLED
    elif kind == "stopped":
        row.status = AllocationStatus.STOPPED
    elif kind == "wrong-pod":
        core.read_namespaced_pod.return_value.metadata.labels["user-id"] = "2"
    db.commit()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/resource/{row.container_id}/ssh-tunnel", headers=headers):
            pass
    assert not destinations


def test_tool_download_is_scoped_and_contains_no_credentials(setup):
    client, row, core, destinations = setup
    assert client.get(f"/resource/{row.container_id}/ssh-tool").status_code == 401
    assert client.get(f"/resource/{row.container_id}/ssh-tool", headers=auth(2)).status_code == 404
    tool = client.get(f"/resource/{row.container_id}/ssh-tool", headers=auth()).json()["data"]
    compile(tool["content"], tool["filename"], "exec")
    assert 'DEFAULT_INSTANCE = "tunnel-owned"' in tool["content"]
    assert create_access_token({"sub": "1"}) not in tool["content"]
    assert not destinations
