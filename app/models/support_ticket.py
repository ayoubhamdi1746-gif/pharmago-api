import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, JSON, Column, ForeignKey
from app.database import Base, StrUUID

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(StrUUID, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    subject = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    category = Column(String(50), default="general")
    priority = Column(String(20), default="normal")
    status = Column(String(20), default="open", index=True)
    assigned_to = Column(String(36), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(StrUUID, primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(StrUUID, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(StrUUID, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    message = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
