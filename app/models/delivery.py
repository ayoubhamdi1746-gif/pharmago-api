import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, func, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[str] = mapped_column(String(36), ForeignKey("prescriptions.id"), nullable=False)
    driver_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    pharmacy_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    otp_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryTicket(Base):
    __tablename__ = "delivery_tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id"), nullable=False)
    pickup_coords: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_dropoff: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    driver_token_hash: Mapped[str] = mapped_column(String(64), ForeignKey("vetted_drivers.driver_token_hash"), nullable=False)
    is_fulfilled: Mapped[bool] = mapped_column(Integer, default=0)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_otp_attempts: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None


class VettedDriver(Base):
    __tablename__ = "vetted_drivers"

    driver_token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    issuing_pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    license_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    license_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Integer, default=1)