import uuid, enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Numeric, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class PaymentProvider(str, enum.Enum):
    KONNECT = "KONNECT"
    FLOUCI = "FLOUCI"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("pharmacy_subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[PaymentProvider] = mapped_column(SAEnum(PaymentProvider), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount_tnd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
