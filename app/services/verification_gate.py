import uuid
import structlog
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription import Prescription, PrescriptionVerification
from app.models.pharmacy import LicensedPharmacist
from app.exceptions.handlers import ForbiddenException, NotFoundException
from app.services.verification_helpers import (
    validate_doctor_token, check_controlled_items,
)
from app.logging.cfg import new_ref

logger = structlog.get_logger()
LOCKED = frozenset({"VERIFIED", "DISPENSED"})


async def verify_prescription(
    db: AsyncSession,
    prescription_id: uuid.UUID,
    pharmacist_license_hash: str,
    doctor_signed_token: str | None = None,
    ref: str | None = None,
) -> PrescriptionVerification:
    if ref is None:
        ref = new_ref()

    result = await db.execute(
        select(LicensedPharmacist).where(
            LicensedPharmacist.pharmacist_license_hash == pharmacist_license_hash,
            LicensedPharmacist.is_active == True,
        )
    )
    if not result.scalar_one_or_none():
        raise ForbiddenException("Pharmacist not licensed or inactive", ref)

    pv_result = await db.execute(
        select(PrescriptionVerification).where(
            PrescriptionVerification.prescription_id == prescription_id
        )
    )
    pv = pv_result.scalar_one_or_none()
    if not pv:
        raise NotFoundException("Prescription verification not found", ref)

    if pv.status == "HIGH_RISK_PENDING":
        if not doctor_signed_token:
            raise ForbiddenException("HIGH_RISK_PENDING requires doctor_signed_token", ref)
        await validate_doctor_token(db, prescription_id, doctor_signed_token, ref)
        pv.status = "PENDING"

    if pv.status in LOCKED:
        raise ForbiddenException(f"Cannot modify prescription in status {pv.status}", ref)

    if pv.status != "PENDING":
        raise ForbiddenException(f"Cannot verify prescription in status {pv.status}", ref)

    presc = await db.get(Prescription, prescription_id)
    controlled = await check_controlled_items(db, presc.medications if presc else [])
    if controlled and pv.pharmacist_license_hash is not None:
        if pv.pharmacist_license_hash == pharmacist_license_hash:
            raise ForbiddenException("Second pharmacist required for controlled substance", ref)
        pv.status = "VERIFIED"
        pv.verified_at = datetime.utcnow()
    elif controlled:
        pv.pharmacist_license_hash = pharmacist_license_hash
    else:
        pv.status = "VERIFIED"
        pv.verified_at = datetime.utcnow()

    await db.commit()
    logger.info("Prescription verified", ref=ref, presc=str(prescription_id))
    return pv
