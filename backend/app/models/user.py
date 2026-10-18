"""
用户模型
"""
from sqlalchemy import Column, BigInteger, Integer, String, Numeric, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class UserStatus(str, enum.Enum):
    """用户状态枚举"""
    ACTIVE = "active"
    DISABLED = "disabled"
    BANNED = "banned"


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True, index=True, comment="用户ID")
    username = Column(String(64), unique=True, nullable=True, comment="用户名")
    email = Column(String(128), unique=True, nullable=True, index=True, comment="邮箱")
    phone = Column(String(32), unique=True, nullable=True, index=True, comment="手机号")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    auth_version = Column(Integer, nullable=False, default=0, server_default="0")
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, default=2, comment="角色ID，默认2=user")
    balance = Column(Numeric(12, 4), nullable=False, default=0.0000, comment="余额")
    status = Column(
        Enum(UserStatus, native_enum=False, create_constraint=False, length=20, values_callable=lambda x: [e.value for e in x]),
        default=UserStatus.ACTIVE,
        nullable=False,
        comment="状态"
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")
    last_login = Column(DateTime(timezone=True), nullable=True, comment="最后登录时间")
    debt_started_at = Column(DateTime(timezone=True), nullable=True)
    grace_expires_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, comment="软删除时间")
    storage_default_bytes = Column(BigInteger, nullable=True, comment="首次分配后冻结的默认存储额度")
    
    # 关系
    role_obj = relationship("Role", back_populates="users")
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    ssh_keys = relationship("SSHKey", back_populates="user", cascade="all, delete-orphan")
    
    @property
    def role(self) -> str:
        """获取角色名称（兼容旧代码）"""
        return self.role_obj.name if self.role_obj else "user"
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role_id={self.role_id})>"

