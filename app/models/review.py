import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, Column, ForeignKey
from app.database import Base, StrUUID

class Review(Base):
    __tablename__ = "reviews"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    author_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(String(36), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))
