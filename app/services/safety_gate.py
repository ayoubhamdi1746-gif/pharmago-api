import uuid
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription import Prescription, DoctorConfirmationRequest
from app.models.pharmacy import LethalRiskSubstance
from app.config import settings

logger = structlog.get_logger()


async def check_safety_gate(
    db: AsyncSession,
    prescription_id: uuid.UUID,
    patient_weight_kg: float,
    ref: str,
) -> str:
    prescription = await db.get(Prescription, prescription_id)
    if not prescription:
        return "PENDING"

    items = prescription.medications if isinstance(prescription.medications, list) else []
    for item in items:
        result = await db.execute(
            select(LethalRiskSubstance).where(
                LethalRiskSubstance.dpm_code == item.get("dpm_code", "")
            )
        )
        substance = result.scalar_one_or_none()
        if not substance:
            continue

        dose_mg = float(item.get("dose_mg", 0))
        quantity = int(item.get("quantity", 0))
        dose_total = dose_mg * quantity
        dose_per_kg = dose_total / patient_weight_kg if patient_weight_kg > 0 else float("inf")

        if dose_per_kg > substance.ld50_threshold_mg_per_kg * settings.SAFETY_LD50_FACTOR:
            logger.info("Safety gate triggered: LD50 threshold exceeded", ref=ref, presc=prescription_id)
            return "HIGH_RISK_PENDING"

        if substance.suicide_risk_flag and substance.single_course_limit is not None:
            if quantity > substance.single_course_limit:
                logger.info("Safety gate triggered: suicide risk quantity", ref=ref, presc=prescription_id)
                return "HIGH_RISK_PENDING"

    return "PENDING"


async def create_doctor_confirmation_request(
    db: AsyncSession,
    prescription_id: uuid.UUID,
    doctor_license_hash: str,
    ref: str,
) -> DoctorConfirmationRequest:
    from datetime import datetime, timedelta

    dcr = DoctorConfirmationRequest(
        prescription_id=prescription_id,
        doctor_license_hash=doctor_license_hash,
        expires_at=datetime.utcnow() + timedelta(hours=settings.DOCTOR_TOKEN_TTL_HOURS),
    )
    db.add(dcr)
    await db.commit()
    logger.info("Doctor confirmation request created", ref=ref, presc=prescription_id)
    return dcr
