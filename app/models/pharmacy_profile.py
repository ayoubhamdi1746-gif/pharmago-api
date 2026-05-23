import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base, StrUUID

class PharmacyProfile(Base):
    __tablename__ = "pharmacy_profiles"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(StrUUID, ForeignKey("users.id"), nullable=False)
    pharmacy_name = Column(String(200), nullable=False)
    city = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    logo_url = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())