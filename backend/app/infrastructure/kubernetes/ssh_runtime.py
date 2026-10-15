"""只在实例临时运行卷中写密码散列；可对旧实例原地启用密码连接。"""
SSH_PASSWORD_SETUP = r'''
import os,signal,time
from pathlib import Path
from tempfile import NamedTemporaryFile
def atomic(path, text):
    with NamedTemporaryFile(mode="w", dir=path.parent, prefix=".credential-", delete=False) as temporary:
        temporary.write(text)
        temporary.flush()
        os.fchmod(temporary.fileno(), 0o600)
        name = temporary.name
    Path(name).replace(path)
hashed = globals().get("PASSWORD_HASH") or Path("/run/platform-auth/password_hash").read_text().strip()
if not hashed.startswith("$6$") or "\n" in hashed:
    raise RuntimeError("Invalid SSH credential")
runtime = Path("/run/platform-ssh")
runtime.mkdir(parents=True, exist_ok=True)
shadow = Path("/etc/shadow")
try:
    rows = shadow.read_text().splitlines()
except FileNotFoundError:
    rows = []
rows = [row for row in rows if not row.startswith("root:")]
rows.append("root:" + hashed + ":" + str(int(time.time() // 86400)) + ":0:99999:7:::")
target = runtime / "shadow"
atomic(target, "\n".join(rows) + "\n")
if not shadow.is_symlink() or os.readlink(shadow) != str(target):
    shadow.unlink(missing_ok=True)
    shadow.symlink_to(target)
config = runtime / "sshd_config"
if config.is_file():
    lines = [line for line in config.read_text().splitlines() if line.split(" ",1)[0] not in ("PasswordAuthentication","PermitRootLogin","UsePAM")]
    lines.extend(["PasswordAuthentication yes","PermitRootLogin yes","UsePAM no"])
    atomic(config, "\n".join(lines) + "\n")
    pid = runtime / "sshd.pid"
    if pid.is_file():
        os.kill(int(pid.read_text().strip()), signal.SIGHUP)
print("SSH_PASSWORD_READY")
'''
