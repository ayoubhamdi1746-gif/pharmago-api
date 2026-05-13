import uuid
from datetime import datetime
from sqlalchemy import String, Float, Boolean, DateTime, Integer, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from app.database import Base


class LicensedPharmacist(Base):
    __tablename__ = "licensed_pharmacists"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pharmacist_license_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)


class ControlledSubstance(Base):
    __tablename__ = "controlled_substances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dpm_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    generic_name: Mapped[str] = mapped_column(String(300), nullable=False)
    requires_dual_approval: Mapped[bool] = mapped_column(Boolean, default=False)


class LethalRiskSubstance(Base):
    __tablename__ = "lethal_risk_substances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dpm_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    generic_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ld50_threshold_mg_per_kg: Mapped[float] = mapped_column(Float, nullable=False)
    suicide_risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    single_course_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
