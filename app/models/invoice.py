import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, Text, Boolean, DateTime, JSON, Column
from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id = Column(String(36), nullable=False, index=True)
    invoice_number = Column(String(50), nullable=False, unique=True)
    plan_name = Column(String(50), nullable=False)
    amount_tnd = Column(Numeric(10, 2), nullable=False)
    tax_tnd = Column(Numeric(10, 2), default=Decimal("0.00"))
    total_tnd = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), default="pending")
    paid_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=False)
    line_items = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
