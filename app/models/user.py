import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
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
