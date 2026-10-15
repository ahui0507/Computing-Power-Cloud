"""
安全相关工具函数
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError
from app.core.config import settings

INITIAL_ACCOUNT_PASSWORD = settings.INITIAL_ACCOUNT_PASSWORD

# 尝试使用passlib，如果失败则使用bcrypt直接
try:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
    USE_PASSLIB = True
except Exception:
    # 如果passlib有问题，直接使用bcrypt
    import bcrypt

    USE_PASSLIB = False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        if USE_PASSLIB:
            return pwd_context.verify(plain_password, hashed_password)
        else:
            # 直接使用bcrypt
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    生成密码哈希
    注意：bcrypt限制密码长度不能超过72字节
    """
    if not password or str(password).startswith("REPLACE_"):
        raise ValueError("Account password must be explicitly configured")

    # 确保密码是字符串
    if isinstance(password, bytes):
        password = password.decode("utf-8")

    # 如果密码超过72字节，截断它
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        password = password_bytes[:72].decode("utf-8", errors="ignore")

    try:
        if USE_PASSLIB:
            return pwd_context.hash(password)
        else:
            # 直接使用bcrypt
            import bcrypt

            salt = bcrypt.gensalt(rounds=12)
            hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
            return hashed.decode("utf-8")
    except Exception as e:
        # 如果passlib失败，回退到直接使用bcrypt
        import bcrypt

        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建JWT访问令牌

    Args:
        data: 要编码的数据（通常包含user_id等）
        expires_delta: 过期时间增量，如果为None则使用默认值

    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """创建刷新令牌"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码JWT令牌

    Args:
        token: JWT令牌字符串

    Returns:
        解码后的数据字典，如果解码失败返回None
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except ExpiredSignatureError:
        # Token 已过期
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("Token expired")
        return None
    except JWTClaimsError as e:
        # Token 声明错误（签名错误、格式错误等）
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "JWT claims validation failed"
        )
        return None
    except JWTError as e:
        # 其他 JWT 错误（包括签名错误等）
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "JWT signature or format validation failed"
        )
        return None
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error decoding token: {str(e)}, type: {type(e).__name__}")
        return None
