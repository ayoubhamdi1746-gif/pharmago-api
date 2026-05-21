import uuid, structlog, hmac, hashlib
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import ControlledSubstance, LethalRiskSubstance
from app.exceptions.handlers import NotFoundException
from app.logging.cfg import new_ref
from app.config import settings
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


def _resolve_drug_name(dpm_code: str, controlled_map: dict, lethal_map: dict) -> str:
    if dpm_code in controlled_map:
        return controlled_map[dpm_code]
    if dpm_code in lethal_map:
        return lethal_map[dpm_code]
    return dpm_code


@router.get("/confirmations")
@limiter.limit("20/minute")
async def doctor_confirmations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DOCTOR)),
):
    ref = new_ref()
    rows = (await db.execute(
        select(DoctorConfirmationRequest).where(
            DoctorConfirmationRequest.doctor_license_hash == user.id
        )
    )).scalars().all()

    presc_ids = [r.prescription_id for r in rows]
    presc_rows = (await db.execute(
        select(Prescription).where(Prescription.id.in_(presc_ids))
    )).scalars().all() if presc_ids else []
    presc_map = {p.id: p for p in presc_rows}

    controlled_rows = (await db.execute(select(ControlledSubstance))).scalars().all()
    controlled_map = {s.dpm_code: s.generic_name for s in controlled_rows}
    lethal_rows = (await db.execute(select(LethalRiskSubstance))).scalars().all()
    lethal_map = {s.dpm_code: s.generic_name for s in lethal_rows}

    items = []
    for r in rows:
        presc = presc_map.get(r.prescription_id)
        medicament = ""
        dosage = ""
        if presc and presc.medications:
            first = presc.medications[0] if isinstance(presc.medications, list) else presc.medications
            code = first.get("dpm_code", first.get("name", ""))
            medicament = _resolve_drug_name(code, controlled_map, lethal_map)
            dose = first.get("dose_mg", first.get("dosage", 0))
            unit = first.get("unit", "mg")
            dosage = f"{dose} {unit}" if dose else ""

        items.append({
            "id": str(r.id),
            "prescription_id": str(r.prescription_id),
            "medicament": medicament,
            "dosage": dosage,
            "doctor_license_hash": r.doctor_license_hash,
            "status": r.status,
            "expires_at": r.expires_at.isoformat(),
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "patient_id": presc.patient_id if presc else None,
        })

    return APIResponse(status="ok", message="طلبات التأكيد", data={"confirmations": items}, ref=ref)


@router.post("/confirm/{prescription_id}")
@limiter.limit("10/minute")
async def doctor_confirm_prescription(
    prescription_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DOCTOR)),
):
    ref = new_ref()
    dcr = (await db.execute(
        select(DoctorConfirmationRequest).where(
            DoctorConfirmationRequest.prescription_id == prescription_id,
            DoctorConfirmationRequest.status == "AWAITING",
        )
    )).scalar_one_or_none()
    if not dcr:
        raise NotFoundException("No pending confirmation request", ref)

    payload = f"{prescription_id}:{user.id}:{dcr.requested_at.isoformat()}"
    signed_token = hmac.new(settings.HMAC_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

    dcr.signed_token_hash = hashlib.sha256(signed_token.encode()).hexdigest()
    dcr.status = "SIGNED"
    pv = (await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.prescription_id == prescription_id)
    )).scalar_one_or_none()
    if pv and pv.status == "HIGH_RISK_PENDING":
        pv.status = "PENDING"
    await db.commit()
    return APIResponse(status="ok", message="تم تأكيد الوصفة", data={"status": "PENDING"}, ref=ref)
