import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, Integer, func, LargeBinary, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base, StrUUID


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    driver_id: Mapped[str] = mapped_column(StrUUID, ForeignKey("users.id"), nullable=False, index=True)
    pharmacy_id: Mapped[str] = mapped_column(StrUUID, ForeignKey("users.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(StrUUID, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="assigned", index=True)
    otp_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_locked(self) -> bool:
        return self.failed_otp_attempts >= 5 and self.locked_at is not None

    def increment_failed_attempts(self) -> bool:
        self.failed_otp_attempts = (self.failed_otp_attempts or 0) + 1
        if self.failed_otp_attempts >= 5:
            self.locked_at = datetime.utcnow()
            return True
        return False


class DeliveryTicket(Base):
    __tablename__ = "delivery_tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    pickup_coords: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_dropoff: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    driver_token_hash: Mapped[str] = mapped_column(String(64), ForeignKey("vetted_drivers.driver_token_hash"), nullable=False, index=True)
    is_fulfilled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    issuing_pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    license_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    license_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)