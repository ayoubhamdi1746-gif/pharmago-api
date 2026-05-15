import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean
from app.database import Base


class DemoRequest(Base):
    __tablename__ = "demo_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    pharmacy = Column(String(255), nullable=False)
    city = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    is_processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)