import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_reference_token: Mapped[str] = mapped_column(String(64), nullable=False)
    items: Mapped[dict] = mapped_column(JSON, nullable=False)
    doctor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doctor_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    doctor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pharmacy_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class PrescriptionVerification(Base):
    __tablename__ = "prescription_verifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    pharmacist_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    pharmacist_license_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    dispensed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class DoctorConfirmationRequest(Base):
    __tablename__ = "doctor_confirmation_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prescriptions.id"), nullable=False)
    doctor_license_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    signed_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="AWAITING")
