import uuid, hmac, hashlib, structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.limiter import limiter
from app.schemas.common import APIResponse, PrescriptionCreate, DoctorConfirmRequest
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.patient import MedicalRecord
from app.models.pharmacy import ControlledSubstance, LethalRiskSubstance
from app.services.safety_gate import check_safety_gate, create_doctor_confirmation_request
from app.exceptions.handlers import NotFoundException, ForbiddenException
from app.logging.cfg import new_ref
from app.config import settings


async def _resolve_items(db: AsyncSession, items: list[dict]) -> list[dict]:
    controlled = await db.execute(select(ControlledSubstance))
    lethal = await db.execute(select(LethalRiskSubstance))
    name_to_code = {}
    for s in controlled.scalars().all():
        name_to_code[s.generic_name.lower()] = s.dpm_code
        name_to_code[s.dpm_code.lower()] = s.dpm_code
    for s in lethal.scalars().all():
        name_to_code[s.generic_name.lower()] = s.dpm_code
        name_to_code[s.dpm_code.lower()] = s.dpm_code
    resolved = []
    for it in items:
        code = (it.get("dpm_code") or "").strip()
        med_name = (it.get("medication_name") or "").strip()
        lookup_key = (code or med_name).lower()
        if lookup_key in name_to_code:
            it["dpm_code"] = name_to_code[lookup_key]
        elif med_name and not code:
            it["dpm_code"] = med_name
        elif not code:
            it["dpm_code"] = med_name or "UNKNOWN"
        resolved.append(it)
    return resolved

router = APIRouter()
logger = structlog.get_logger()


@router.post("", status_code=201)
async def create_prescription(
    body: PrescriptionCreate, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    ref = new_ref()
    raw_items = [i.model_dump() for i in body.items]
    resolved_items = await _resolve_items(db, raw_items)
    presc = Prescription(
        patient_reference_token=user.id,
        items=resolved_items,
        doctor_name=body.doctor_name,
        doctor_phone=body.doctor_phone,
        doctor_email=body.doctor_email,
        pharmacy_id=body.pharmacy_id,
    )
    db.add(presc)
    await db.commit()
    await db.refresh(presc)

    rec = (await db.execute(
        select(MedicalRecord).where(MedicalRecord.reference_token == user.id)
    )).scalar_one_or_none()
    weight = rec.patient_weight_kg if rec else 70.0

    status = await check_safety_gate(db, presc.id, weight, ref)
    pv = PrescriptionVerification(prescription_id=presc.id, status=status)
    db.add(pv)
    if status == "HIGH_RISK_PENDING":
        await create_doctor_confirmation_request(db, presc.id, "", ref)
    await db.commit()

    return APIResponse(status="ok", message="تم رفع الوصفة بنجاح", data={"prescription_id": str(presc.id), "status": status}, ref=ref)


@router.get("/{prescription_id}/status")
async def get_prescription_status(
    prescription_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    ref = new_ref()
    presc = await db.get(Prescription, prescription_id)
    if not presc or presc.patient_reference_token != user.id:
        raise NotFoundException("Prescription not found", ref)
    pv = (await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.prescription_id == prescription_id)
    )).scalar_one_or_none()
    return APIResponse(status="ok", message="حالة الوصفة", data={
        "prescription_id": str(prescription_id), "status": pv.status if pv else "UNKNOWN",
    }, ref=ref)


@router.post("/{prescription_id}/doctor-confirm")
@limiter.limit("10/minute")
async def doctor_confirm(
    prescription_id: uuid.UUID, body: DoctorConfirmRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DOCTOR)),
):
    ref = new_ref()
    signed_token = body.signed_token
    doctor_hash = user.id
    dcr = (await db.execute(
        select(DoctorConfirmationRequest).where(
            DoctorConfirmationRequest.prescription_id == prescription_id,
            DoctorConfirmationRequest.status == "AWAITING",
        )
    )).scalar_one_or_none()
    if not dcr:
        raise NotFoundException("No pending confirmation request", ref)

    payload = f"{prescription_id}:{doctor_hash}:{dcr.requested_at.isoformat()}"
    expected = hmac.new(settings.HMAC_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signed_token):
        raise ForbiddenException("Invalid token for this prescription", ref)

    dcr.signed_token_hash = hashlib.sha256(signed_token.encode()).hexdigest()
    dcr.status = "SIGNED"
    pv = (await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.prescription_id == prescription_id)
    )).scalar_one_or_none()
    if pv and pv.status == "HIGH_RISK_PENDING":
        pv.status = "PENDING"
    await db.commit()
    return APIResponse(status="ok", message="تم تأكيد الوصفة", data={"status": "PENDING"}, ref=ref)
