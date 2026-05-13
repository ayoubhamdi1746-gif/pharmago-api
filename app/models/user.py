import uuid
from sqlalchemy import Column, String, Boolean
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
    email = Column(String(255), nullable=True)
