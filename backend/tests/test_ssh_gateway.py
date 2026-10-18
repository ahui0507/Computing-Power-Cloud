import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.core.exceptions import ClusterOperationError
from app.core.instance_credentials import ssh_password_hash
from app.models import Allocation, AllocationStatus, User, UserStatus
from app.models.operation import AllocationOperation, OperationKind
from app.services.ssh_gateway_service import SSHGatewayService

spec = importlib.util.spec_from_file_location(
    "platform_ssh_gateway_test", Path(__file__).resolve().parents[2] / "deploy/ssh_gateway/platform_ssh_gateway.py",
)
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)


def identity(identifier=9, port=31009):
    return gateway.Identity(identifier, 1, port, ssh_password_hash(identifier, 1))


@pytest.mark.parametrize("identifier,port", [(0, 31009), (-1, 31009), (9, 22), (9, 2222), (9, 8080), (9, 6443), (9, 32768)])
def test_rejects_host_services_and_invalid_id_before_any_mutation(identifier, port):
    accounts, save, policy = MagicMock(), MagicMock(), MagicMock()
    with pytest.raises(ValueError):
        gateway.synchronize([identity(identifier, port)], {}, accounts, save, policy)
    accounts.ensure.assert_not_called()
    save.assert_not_called()
    policy.assert_not_called()


def test_policy_allows_only_one_exact_target_and_denies_host_sessions():
    source = gateway.render_policy([identity()])
    assert source.index("PermitOpen 127.0.0.1:31009") < source.index("PermitOpen none")
    assert "Match User cpjump-9\n" in source
    assert "MaxSessions 0\n" in source and "ForceCommand /usr/sbin/nologin\n" in source
    assert "AllowTcpForwarding local\n" in source and "PermitListen none\n" in source
    assert "AllowStreamLocalForwarding no\n" in source
    assert "$6$" not in source
    with pytest.raises(ValueError):
        gateway.render_policy([identity(), identity(10, 31009)])


def test_expired_identity_is_withdrawn_before_locking_and_revocation_does_not_touch_other_accounts():
    events = []
    registry = {
        "1": {"uid": 501, "user_id": 1, "active": True, "port": 31001},
        "2": {"uid": 502, "user_id": 1, "active": True, "port": 31002},
    }

    class Accounts:
        def ensure(self, value, record, remember):
            events.append(("ensure", value.allocation_id))
            return {"uid": 500 + value.allocation_id, "user_id": value.user_id, "active": True, "port": value.port}
        def revoke(self, identifier, record):
            events.append(("revoke", identifier))

    def policy(values):
        events.append(("policy", [value.allocation_id for value in values]))

    result = gateway.synchronize([identity(1, 31001), identity(3, 31003)], registry, Accounts(), lambda value: None, policy)
    assert events[0] == ("policy", [1]) and events[1] == ("revoke", "2")
    assert registry["2"]["active"] is False and registry["1"]["active"] and registry["3"]["active"]
    assert events[-1] == ("policy", [1, 3])
    assert result == {"active": 2, "revoked": 1}


def test_unmanaged_existing_linux_account_is_never_modified(monkeypatch):
    account = SimpleNamespace(pw_uid=1000, pw_gid=200, pw_shell="/bin/bash", pw_dir="/home/system")
    monkeypatch.setattr(gateway.pwd, "getpwnam", lambda name: account)
    mutations = MagicMock()
    monkeypatch.setattr(gateway, "command", mutations)
    accounts = gateway.HostAccounts.__new__(gateway.HostAccounts)
    accounts.gid = 999
    with pytest.raises(ValueError, match="unmanaged"):
        accounts.ensure(identity(), None, MagicMock())
    with pytest.raises(ValueError, match="unmanaged"):
        accounts.revoke(9, {"uid": 1000})
    mutations.assert_not_called()


def test_only_running_ssh_instances_of_active_users_receive_forwarding_accounts(db, monkeypatch):
    monkeypatch.setattr(settings, "SSH_GATEWAY_ENABLED", True)
    for identifier, user_id, status, enabled in [
        (9, 1, AllocationStatus.ACTIVE, True),
        (10, 2, AllocationStatus.ACTIVE, True),
        (11, 1, AllocationStatus.RELEASED, True),
        (12, 1, AllocationStatus.ACTIVE, False),
    ]:
        db.add(Allocation(id=identifier, request_id=f"gateway-{identifier}", user_id=user_id, node_id=1,
                         pool_id=1, image_id=1, requested_gpu_count=1, gpu_type_id=1,
                         status=status, pod_name=f"pod-{identifier}", ssh_port=31000 + identifier))
        db.flush()
        db.add(AllocationOperation(allocation_id=identifier, kind=OperationKind.CREATE,
                                  payload={"options": {"namespace": "default", "ssh_enabled": enabled}}))
    db.get(User, 2).status = UserStatus.DISABLED
    db.commit()
    assert db.get(User, 1).role == "user"
    values = gateway.desired_identities(db)
    assert [(row.allocation_id, row.user_id, row.port) for row in values] == [(9, 1, 31009)]
    assert values[0].password_hash == ssh_password_hash(9, 1)
    db.get(User, 1).deleted_at = __import__("datetime").datetime.utcnow()
    db.commit()
    assert not gateway.desired_identities(db)


@pytest.mark.parametrize("response", [
    {"ready": True, "username": "system", "port": 31009, "target_host": "127.0.0.1"},
    {"ready": True, "username": "cpjump-9", "port": 2222, "target_host": "127.0.0.1"},
    {"ready": True, "username": "cpjump-9", "port": 31009, "target_host": "192.0.2.1"},
    {"ready": False, "username": "cpjump-9", "port": 31009, "target_host": "127.0.0.1"},
])
def test_api_rejects_a_helper_response_for_another_identity_or_target(monkeypatch, response):
    import json
    import app.services.ssh_gateway_service as service
    result = SimpleNamespace(stdout=json.dumps(response), check_returncode=lambda: None)
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: result)
    with pytest.raises(ClusterOperationError):
        SSHGatewayService.ensure(SimpleNamespace(id=9, ssh_port=31009))
