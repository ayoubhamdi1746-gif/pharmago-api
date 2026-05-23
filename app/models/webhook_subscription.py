import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, JSON, Column
from app.database import Base, StrUUID

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    pharmacy_id = Column(String(36), nullable=True, index=True)
    url = Column(String(500), nullable=False)
    secret = Column(String(128), nullable=False)
    events = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id = Column(String(36), nullable=False, index=True)
    event = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    response_status = Column(String(10), nullable=True)
    response_body = Column(Text, nullable=True)
    success = Column(Boolean, default=False)
    attempt = Column(String(10), default="1")
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
