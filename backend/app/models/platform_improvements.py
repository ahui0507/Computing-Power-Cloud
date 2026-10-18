from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey, JSON
from app.core.database import Base


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    key = Column(String(64), primary_key=True)
    failures = Column(Integer, nullable=False, default=0)
    window_start = Column(DateTime, nullable=False, index=True)


class ResourceQueue(Base):
    __tablename__ = "resource_queue"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    request_id = Column(String(64), nullable=False, unique=True)
    fingerprint = Column(String(64), nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="waiting", index=True)
    created_at = Column(DateTime, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    lease_until = Column(DateTime, nullable=True)
    lease_owner = Column(String(32), nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    container_id = Column(String(100), nullable=True)
    message = Column(String(300), nullable=False, default="等待资源，排队期间不计费")
