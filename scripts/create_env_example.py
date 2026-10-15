"""从仓库模板创建 backend/.env，已有配置保持幂等。"""
import os
from pathlib import Path

backend = Path(__file__).resolve().parents[1] / "backend"
template = backend / ".env.example"
destination = backend / ".env"

if not template.is_file():
    raise SystemExit("找不到 backend/.env.example，请恢复仓库中的配置模板")
try:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(f"配置已存在: {destination}")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(template.read_text(encoding="utf-8-sig"))
    print(f"配置已创建: {destination}")
