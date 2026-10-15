"""为本机或共享工作目录中的多个进程保存同一份随机密钥。"""
import os
import secrets
import time
from pathlib import Path


def load_or_create_secret(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # 同时启动的进程可能在首个进程写入完成之前看到文件。
        for _ in range(20):
            value = path.read_text(encoding="utf-8").strip()
            if len(value) >= 32:
                return value
            time.sleep(0.05)
        raise RuntimeError("持久化密钥文件为空或无效，请核对文件权限")
    else:
        value = secrets.token_urlsafe(48)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        return value
