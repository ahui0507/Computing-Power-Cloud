"""容器操作的能力边界；尚未实现的操作不能只修改数据库状态。"""
from app.core.exceptions import OperationNotSupportedError, ResourceNotFoundError
from app.models.allocation import Allocation


class ContainerService:
    @staticmethod
    async def start_container(db, user_id: int, container_id: str) -> None:
        ContainerService._get_allocation(db, user_id, container_id)
        raise OperationNotSupportedError("实例恢复需要持久化工作目录，目前尚未支持")

    @staticmethod
    async def stop_container(db, user_id: int, container_id: str) -> None:
        ContainerService._get_allocation(db, user_id, container_id)
        raise OperationNotSupportedError("实例暂停尚未支持，请使用释放资源结束实例")

    @staticmethod
    async def restart_container(db, user_id: int, container_id: str) -> None:
        ContainerService._get_allocation(db, user_id, container_id)
        raise OperationNotSupportedError("实例重启需要持久化工作目录，目前尚未支持")

    @staticmethod
    async def resize_container(db, user_id: int, container_id: str, new_gpu_count: int) -> bool:
        allocation = ContainerService._get_allocation(db, user_id, container_id)
        if new_gpu_count == allocation.requested_gpu_count:
            return True
        raise OperationNotSupportedError("运行实例调整 GPU 数量尚未支持")

    @staticmethod
    def _get_allocation(db, user_id: int, container_id: str):
        allocation = (
            db.query(Allocation)
            .filter(Allocation.container_id == container_id, Allocation.user_id == user_id)
            .first()
        )
        if allocation is None:
            raise ResourceNotFoundError("Container")
        return allocation
