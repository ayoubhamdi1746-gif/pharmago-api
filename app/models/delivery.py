import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, LargeBinary, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class DeliveryTicket(Base):
    __tablename__ = "delivery_tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id"), nullable=False)
    pickup_coords: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_dropoff: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    is_fulfilled: Mapped[bool] = mapped_column(Boolean, default=False)
    driver_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class VettedDriver(Base):
    __tablename__ = "vetted_drivers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    driver_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issuing_pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    license_issued_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    license_expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    suspension_reason_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
