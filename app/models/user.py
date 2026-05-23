import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, func, TypeDecorator
from app.database import Base


class StrUUID(TypeDecorator):
    """UUID column that accepts Python str values and stores as native PG UUID"""
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID())
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "postgresql":
            return uuid.UUID(value) if isinstance(value, str) else value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "postgresql":
            return str(value)
        return value


class User(Base):
    __tablename__ = "users"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    role = Column(String(20), nullable=False)
    identity_id = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    pharmacy_id = Column(String(36), nullable=True)
    city = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    full_name = Column(String(255), nullable=True)
    is_verified = Column(Boolean, default=False)
    pharmacist_license_hash = Column(String(64), nullable=True)
