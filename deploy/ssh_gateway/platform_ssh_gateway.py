#!/opt/computing-platform/current/backend/.venv/bin/python
"""Root-only helper: dedicated no-shell accounts can forward to one owned NodePort.

The sudo interface accepts only `ensure ALLOCATION_ID`. A root timer calls `sync`
to lock expired identities and terminate their forwarding sessions. No credentials
are accepted from the caller or printed, and existing host accounts are untouched.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import grp
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile

STATE_ROOT = Path("/var/lib/cpcloud-ssh-gateway")
POLICY_PATH = Path("/etc/ssh/platform-instance-gateway.conf")
GROUP = "cpcloud-ssh-jump"
BACKEND = "/opt/computing-platform/current/backend"


def allocation_id(value):
    if not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)) or int(value) > 2**63 - 1:
        raise ValueError("Invalid allocation ID")
    return int(value)


@dataclass(frozen=True)
class Identity:
    allocation_id: int
    user_id: int
    port: int
    password_hash: str

    @property
    def username(self):
        return f"cpjump-{self.allocation_id}"

    def validate(self):
        allocation_id(self.allocation_id)
        allocation_id(self.user_id)
        if not isinstance(self.port, int) or not 30000 <= self.port <= 32767:
            raise ValueError("Gateway target must be an instance NodePort")
        if not re.fullmatch(r"\$6\$rounds=10000\$[a-z0-9]{16}\$[./A-Za-z0-9]{86}", self.password_hash):
            raise ValueError("Invalid instance credential hash")


def render_policy(identities):
    identities = sorted(identities, key=lambda item: item.allocation_id)
    ids, ports = set(), set()
    lines = ["# Managed by platform-ssh-gateway; never put credentials here."]
    for identity in identities:
        identity.validate()
        if identity.allocation_id in ids or identity.port in ports:
            raise ValueError("Duplicate gateway identity or target")
        ids.add(identity.allocation_id)
        ports.add(identity.port)
        # Specific targets must precede the deny-by-default group below.
        lines.extend([
            f"Match User {identity.username}",
            f"    PermitOpen 127.0.0.1:{identity.port}",
        ])
    lines.extend([
        f"Match Group {GROUP}",
        "    PermitOpen none",
        "    PermitListen none",
        "    MaxSessions 0",
        "    ForceCommand /usr/sbin/nologin",
        "    PermitTTY no",
        "    AllowTcpForwarding local",
        "    AllowStreamLocalForwarding no",
        "    AllowAgentForwarding no",
        "    X11Forwarding no",
        "    PermitTunnel no",
        "    GatewayPorts no",
        "    PasswordAuthentication yes",
        "    KbdInteractiveAuthentication no",
        "    PubkeyAuthentication no",
        "    AuthenticationMethods password",
        "    PermitUserRC no",
    ])
    return "\n".join(lines) + "\n"


def atomic_write(path, content, mode):
    if path.is_symlink():
        raise ValueError("Managed path cannot be a symlink")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fchmod(temporary.fileno(), mode)
        os.fsync(temporary.fileno())
        name = temporary.name
    os.replace(name, path)


def command(arguments, **kwargs):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=15, **kwargs)


class HostAccounts:
    def __init__(self):
        self.gid = grp.getgrnam(GROUP).gr_gid

    def ensure(self, identity, record, remember):
        identity.validate()
        try:
            account = pwd.getpwnam(identity.username)
        except KeyError:
            if record:
                raise ValueError("Managed account was removed outside the gateway")
            command([
                "useradd", "--system", "--no-create-home", "--gid", GROUP,
                "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin",
                "--comment", "CPCloud instance forwarding", identity.username,
            ])
            account = pwd.getpwnam(identity.username)
            record = {"uid": account.pw_uid, "user_id": identity.user_id, "active": False}
            # If interrupted, the newly created account is still locked and recorded.
            remember(identity.allocation_id, record)
        if (
            not record or record["uid"] != account.pw_uid or record["user_id"] != identity.user_id
            or account.pw_uid == 0 or account.pw_gid != self.gid
            or account.pw_shell != "/usr/sbin/nologin" or account.pw_dir != "/nonexistent"
        ):
            raise ValueError("Refusing to modify an unmanaged host account")
        import spwd
        if not hmac.compare_digest(spwd.getspnam(identity.username).sp_pwdp, identity.password_hash):
            # Send only the hash through stdin; never place a password/hash in argv.
            command(["chpasswd", "--encrypted"], input=identity.username + ":" + identity.password_hash + "\n")
        return {**record, "active": True, "port": identity.port}

    def revoke(self, identifier, record):
        username = f"cpjump-{allocation_id(identifier)}"
        try:
            account = pwd.getpwnam(username)
        except KeyError:
            return
        if account.pw_uid != record["uid"] or account.pw_uid == 0 or account.pw_gid != self.gid:
            raise ValueError("Refusing to revoke an unmanaged host account")
        command(["usermod", "--lock", username])
        # Accounts remain locked, preventing UID reuse. No user directories are removed.
        result = subprocess.run(["pkill", "-KILL", "-u", str(account.pw_uid)], capture_output=True, timeout=10)
        if result.returncode not in (0, 1):
            raise RuntimeError("Could not close gateway sessions")


def install_policy(identities, path=POLICY_PATH):
    source = render_policy(identities)
    old = path.read_text() if path.exists() else None
    if old == source:
        return
    atomic_write(path, source, 0o644)
    try:
        command(["/usr/sbin/sshd", "-t"])
        command(["systemctl", "reload", "ssh.service"])
    except Exception:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, old, 0o644)
        # Restore the previous validated policy without stopping existing SSH sessions.
        subprocess.run(["systemctl", "reload", "ssh.service"], capture_output=True, timeout=15)
        raise


def synchronize(identities, registry, accounts, save, policy):
    identities = list(identities)
    render_policy(identities)  # Validate all input before any host mutation.
    desired = {str(identity.allocation_id): identity for identity in identities}
    revoked = [key for key, record in registry.items() if record.get("active") and key not in desired]
    if revoked:
        # Withdraw old targets before locking credentials or terminating processes.
        policy([identity for key, identity in desired.items() if registry.get(key, {}).get("active")])
        for key in revoked:
            accounts.revoke(key, registry[key])
            registry[key]["active"] = False
            save(registry)

    def remember(identifier, record):
        registry[str(identifier)] = record
        save(registry)

    for key, identity in desired.items():
        registry[key] = accounts.ensure(identity, registry.get(key), remember)
        save(registry)
    policy(identities)
    return {"active": len(identities), "revoked": len(revoked)}


def desired_identities(db):
    from app.core.config import settings
    from app.core.instance_credentials import ssh_password_hash
    from app.models import Allocation, AllocationStatus, User, UserStatus
    from app.services.access_service import AccessService
    if not settings.SSH_GATEWAY_ENABLED:
        return []
    allocations = db.query(Allocation).join(User, User.id == Allocation.user_id).filter(
        Allocation.status == AllocationStatus.ACTIVE,
        User.status == UserStatus.ACTIVE,
        User.deleted_at.is_(None),
    ).all()
    return [
        Identity(row.id, row.user_id, row.ssh_port, ssh_password_hash(row.id, row.user_id))
        for row in allocations
        if row.ssh_port and AccessService.allocation_options(row).get("ssh_enabled")
    ]


def load_desired():
    os.environ["PLATFORM_ENV_FILE"] = "/etc/cpcloud/backend.env"
    sys.path.insert(0, BACKEND)
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        return desired_identities(db)


@contextmanager
def locked_state():
    STATE_ROOT.mkdir(mode=0o700, exist_ok=True)
    if STATE_ROOT.is_symlink() or STATE_ROOT.stat().st_uid != 0 or STATE_ROOT.stat().st_mode & 0o077:
        raise ValueError("Gateway state must be private and root-owned")
    with (STATE_ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = STATE_ROOT / "accounts.json"
        if path.is_symlink():
            raise ValueError("Invalid registry path")
        registry = json.loads(path.read_text()) if path.exists() else {}
        yield registry, lambda value: atomic_write(path, json.dumps(value, sort_keys=True), 0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("ensure", "sync"))
    parser.add_argument("allocation", nargs="?", type=allocation_id)
    arguments = parser.parse_args()
    if os.geteuid() != 0 or (arguments.action == "ensure") != (arguments.allocation is not None):
        parser.error("Invalid privileged gateway invocation")
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    with locked_state() as (registry, save):
        identities = load_desired()
        selected = next((item for item in identities if item.allocation_id == arguments.allocation), None)
        if arguments.action == "ensure" and selected is None:
            raise ValueError("Instance is not eligible for SSH forwarding")
        result = synchronize(identities, registry, HostAccounts(), save, install_policy)
    if selected:
        result = {"ready": True, "username": selected.username, "port": selected.port, "target_host": "127.0.0.1"}
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Root-helper exceptions/commands can include hashes: never echo them.
        print("SSH gateway synchronization failed", file=sys.stderr)
        raise SystemExit(1)
