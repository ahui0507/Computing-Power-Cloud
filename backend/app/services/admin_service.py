"""
管理员服务
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from app.models.user import User, UserStatus
from app.models.role import Role
from app.models.resource_pool import ResourcePool
from app.models.node import Node, GPU
from app.models.gpu_type import GPUType
from app.core.exceptions import ResourceNotFoundError, ResourceConflictError
from app.core.security import get_password_hash, INITIAL_ACCOUNT_PASSWORD
from app.core.audit import audit
from app.services.storage_quota_service import StorageQuotaService
from app.services.storage_service import StorageService


class AdminService:
    """管理员服务类"""

    @staticmethod
    def create_user(db: Session, admin: User, email: str) -> User:
        if db.query(User.id).filter(func.lower(User.email) == email).first():
            raise ResourceConflictError("该邮箱账号已存在，请刷新用户列表")
        role = db.query(Role).filter_by(name="user").first()
        if not role:
            raise ResourceNotFoundError("普通用户角色")
        user = User(
            email=email,
            role_id=role.id,
            password_hash=get_password_hash(INITIAL_ACCOUNT_PASSWORD),
            balance=0,
            status=UserStatus.ACTIVE,
        )
        try:
            db.add(user)
            db.flush()
            StorageQuotaService.prepare(db, user.id)
            StorageService.user_root(user.id)
            audit(db, admin, "创建用户", "user", user.id, detail={"email": email})
            db.commit()
            db.refresh(user)
        except IntegrityError as error:
            db.rollback()
            raise ResourceConflictError("该邮箱账号已存在，请刷新用户列表") from error
        except Exception:
            db.rollback()
            raise
        return user

    @staticmethod
    def get_all_users(db: Session):
        """获取所有用户"""
        return db.query(User).filter(User.deleted_at.is_(None)).all()

    @staticmethod
    def set_user_role(db: Session, user_id: int, role: str) -> None:
        """设置用户角色"""
        admin_role = db.query(Role).filter(Role.name == "admin").one()
        admins = (
            db.query(User)
            .filter(User.role_id == admin_role.id, User.deleted_at.is_(None))
            .order_by(User.id)
            .with_for_update()
            .all()
        )
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ResourceNotFoundError("User")
        if user.role_id == admin_role.id and role != "admin" and len(admins) <= 1:
            raise ResourceConflictError("必须保留至少一名管理员")

        # 查找角色
        role_obj = db.query(Role).filter(Role.name == role).first()
        if not role_obj:
            raise ResourceNotFoundError("Role")

        user.role_id = role_obj.id
        db.commit()

    @staticmethod
    def create_resource_pool(db: Session, name: str, gpu_type: str, node_ids: list) -> ResourcePool:
        """创建资源池"""
        # 查找GPU类型（支持大小写不敏感）
        gpu_type_code = gpu_type.upper().strip()
        gpu_type_obj = db.query(GPUType).filter(GPUType.code == gpu_type_code).first()
        if not gpu_type_obj:
            # 列出所有可用的GPU类型
            available_types = [gt.code for gt in db.query(GPUType).all()]
            raise ResourceNotFoundError(
                f"GPU类型 '{gpu_type}' 不存在。可用的类型: {', '.join(available_types)}"
            )

        # 验证节点存在
        nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
        if len(nodes) != len(node_ids):
            raise ResourceNotFoundError("Some nodes not found")

        # 计算总GPU数（匹配GPU类型）
        total_gpus = (
            db.query(GPU)
            .filter(and_(GPU.node_id.in_(node_ids), GPU.gpu_type_id == gpu_type_obj.id))
            .count()
        )

        pool = ResourcePool(
            name=name,
            gpu_type_id=gpu_type_obj.id,
            node_ids=node_ids,
            total_gpus=total_gpus,
            free_gpus=total_gpus,
        )
        db.add(pool)
        db.commit()
        db.refresh(pool)

        return pool
