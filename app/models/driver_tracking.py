import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Boolean, DateTime, Column, ForeignKey
from app.database import Base


class DriverLocation(Base):
    __tablename__ = "driver_locations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    driver_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    delivery_id = Column(String(36), nullable=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    speed = Column(Float, nullable=True)
    bearing = Column(Float, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
