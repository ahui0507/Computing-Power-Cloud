"""为不同实例生成独立访问凭证，凭证只提供给所属用户。"""
import hashlib
import hmac
from urllib.parse import urlencode

from app.core.config import settings


class JupyterService:
    @staticmethod
    def token(allocation_id: int, user_id: int) -> str:
        payload = f"jupyter:{allocation_id}:{user_id}".encode("utf-8")
        return hmac.new(settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def authenticated_url(url: str, allocation_id: int, user_id: int):
        if not url:
            return None
        return f"{url}?{urlencode({'token': JupyterService.token(allocation_id, user_id)})}"
