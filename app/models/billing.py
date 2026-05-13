import uuid
import enum
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Numeric, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class SubscriptionPlan(str, enum.Enum):
    STARTER = "STARTER"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class CommissionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COLLECTED = "COLLECTED"


class DriverPayoutStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"


PLAN_PRICES = {
    SubscriptionPlan.STARTER: Decimal("200.00"),
    SubscriptionPlan.PRO: Decimal("450.00"),
    SubscriptionPlan.ENTERPRISE: Decimal("900.00"),
}

PLAN_LIMITS = {
    SubscriptionPlan.STARTER: 50,
    SubscriptionPlan.PRO: None,
    SubscriptionPlan.ENTERPRISE: None,
}


class PharmacySubscription(Base):
    __tablename__ = "pharmacy_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pharmacy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    responsible_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[SubscriptionPlan] = mapped_column(SAEnum(SubscriptionPlan), nullable=False)
    price_tnd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_count_this_month: Mapped[int] = mapped_column(Integer, default=0)
    delivery_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_delivery_earnings: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))


class DeliveryCommission(Base):
    __tablename__ = "delivery_commissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    delivery_ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("delivery_tickets.id"), nullable=False)
    commission_amount_tnd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("2.50"))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    status: Mapped[CommissionStatus] = mapped_column(SAEnum(CommissionStatus), default=CommissionStatus.PENDING)


class DriverPayout(Base):
    __tablename__ = "driver_payouts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    driver_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("delivery_tickets.id"), nullable=False)
    amount_tnd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("3.00"))
    status: Mapped[DriverPayoutStatus] = mapped_column(SAEnum(DriverPayoutStatus), default=DriverPayoutStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
