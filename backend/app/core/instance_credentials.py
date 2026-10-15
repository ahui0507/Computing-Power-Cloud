"""实例凭据由持久化平台密钥独立派生；不写入镜像或业务日志。"""
import base64
import hashlib
import hmac

from passlib.hash import sha512_crypt
from app.core.config import settings


def ssh_password(allocation_id, user_id):
    value = hmac.new(settings.SECRET_KEY.encode(), f"ssh-password:{user_id}:{allocation_id}".encode(), hashlib.sha256).digest()
    return "Cp" + base64.urlsafe_b64encode(value).decode().rstrip("=")[:20] + "9"


def ssh_password_hash(allocation_id, user_id):
    salt = hashlib.sha256(f"ssh-salt:{allocation_id}:{user_id}".encode()).hexdigest()[:16]
    return sha512_crypt.hash(ssh_password(allocation_id, user_id), salt=salt, rounds=10000)
