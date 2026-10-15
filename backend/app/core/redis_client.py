"""
Redis客户端
"""
import redis
from typing import Optional
from app.core.config import settings

redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """
    获取Redis客户端实例（单例模式）
    """
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            username=settings.REDIS_USERNAME,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return redis_client


def close_redis():
    """关闭Redis连接"""
    global redis_client
    if redis_client:
        redis_client.close()
        redis_client = None

