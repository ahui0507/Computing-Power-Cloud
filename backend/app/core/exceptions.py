"""
自定义异常类
"""
from fastapi import HTTPException, status


class ComputingPlatformException(HTTPException):
    """平台基础异常类"""

    pass


class AuthenticationError(ComputingPlatformException):
    """认证错误"""

    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class AuthorizationError(ComputingPlatformException):
    """授权错误"""

    def __init__(self, detail: str = "Not enough permissions"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ResourceNotFoundError(ComputingPlatformException):
    """资源未找到"""

    def __init__(self, resource: str = "Resource"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")


class ResourceConflictError(ComputingPlatformException):
    """资源冲突"""

    def __init__(self, detail: str = "Resource conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class InsufficientBalanceError(ComputingPlatformException):
    """余额不足"""

    def __init__(self, detail: str = "Insufficient balance"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class InsufficientResourceError(ComputingPlatformException):
    """资源不足"""

    def __init__(self, detail: str = "Insufficient resources"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ClusterUnavailableError(ComputingPlatformException):
    """集群连接不可用，调用方不能将操作视为成功。"""

    def __init__(self, detail: str = "Kubernetes cluster is unavailable"):
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
        self.cleanup_confirmed = True  # 尚未创建任何集群资源


class ClusterOperationError(ComputingPlatformException):
    """集群操作失败；未确认清理时必须保留资源预留。"""

    def __init__(
        self, detail: str, *, cleanup_confirmed: bool = False, cleanup_attempted: bool = False
    ):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
        self.cleanup_confirmed = cleanup_confirmed
        self.cleanup_attempted = cleanup_attempted


class OperationNotSupportedError(ComputingPlatformException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=detail)
