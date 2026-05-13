import uuid
import hmac
import hashlib
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription import PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import ControlledSubstance
from app.exceptions.handlers import ForbiddenException
from app.config import settings

LOCKED = frozenset({"VERIFIED", "DISPENSED"})


async def validate_doctor_token(
    db: AsyncSession,
    prescription_id: uuid.UUID,
    doctor_signed_token: str,
    ref: str,
) -> None:
    result = await db.execute(
        select(DoctorConfirmationRequest).where(
            DoctorConfirmationRequest.prescription_id == prescription_id,
        ).order_by(DoctorConfirmationRequest.requested_at.desc())
    )
    dcr = result.scalar_one_or_none()
    if not dcr:
        raise ForbiddenException("No doctor confirmation request found", ref)

    expires_naive = dcr.expires_at.replace(tzinfo=None)
    if expires_naive < datetime.utcnow():
        dcr.status = "EXPIRED"
        await db.commit()
        raise ForbiddenException("Doctor token expired, re-request sent", ref)

    payload = f"{prescription_id}:{dcr.doctor_license_hash}:{dcr.requested_at.isoformat()}"
    expected = hmac.new(
        settings.HMAC_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, doctor_signed_token):
        raise ForbiddenException("Invalid doctor_signed_token", ref)

    dcr.signed_token_hash = hashlib.sha256(doctor_signed_token.encode()).hexdigest()
    dcr.status = "SIGNED"
    await db.commit()


async def check_controlled_items(db: AsyncSession, items: list) -> bool:
    if not items:
        return False
    codes = [i.get("dpm_code", "") for i in items if isinstance(i, dict)]
    if not codes:
        return False
    result = await db.execute(
        select(ControlledSubstance).where(
            ControlledSubstance.dpm_code.in_(codes),
            ControlledSubstance.requires_dual_approval == True,
        )
    )
    return result.scalar_one_or_none() is not None


async def check_modification_allowed(
    db: AsyncSession, prescription_id: uuid.UUID, ref: str
) -> None:
    result = await db.execute(
        select(PrescriptionVerification).where(
            PrescriptionVerification.prescription_id == prescription_id
        )
    )
    pv = result.scalar_one_or_none()
    if pv and pv.status in LOCKED:
        raise ForbiddenException(f"Cannot modify after {pv.status}", ref)
