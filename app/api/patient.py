import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.pharmacy import ControlledSubstance, LethalRiskSubstance
from app.models.delivery import DeliveryTicket, Delivery
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


def _resolve_drug_name(dpm_code: str, controlled_map: dict, lethal_map: dict) -> str:
    if dpm_code in controlled_map:
        return controlled_map[dpm_code]
    if dpm_code in lethal_map:
        return lethal_map[dpm_code]
    return dpm_code


@router.get("/prescriptions")
@limiter.limit("30/minute")
async def patient_prescriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    ref = new_ref()
    presc_rows = (await db.execute(
        select(Prescription).where(Prescription.patient_id == user.id)
    )).scalars().all()

    presc_ids = [p.id for p in presc_rows]
    pv_rows = (await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.prescription_id.in_(presc_ids))
    )).scalars().all() if presc_ids else []

    controlled_rows = (await db.execute(select(ControlledSubstance))).scalars().all()
    controlled_map = {s.dpm_code: s.generic_name for s in controlled_rows}
    lethal_rows = (await db.execute(select(LethalRiskSubstance))).scalars().all()
    lethal_map = {s.dpm_code: s.generic_name for s in lethal_rows}

    presc_map = {p.id: p for p in presc_rows}
    items = []
    for pv in pv_rows:
        presc = presc_map.get(pv.prescription_id)
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
            "prescription_id": str(pv.prescription_id),
            "status": pv.status,
            "medicament": medicament,
            "dosage": dosage,
            "patient_id": presc.patient_id if presc else None,
            "verified_at": pv.verified_at.isoformat() if pv.verified_at else None,
            "dispensed_at": pv.dispensed_at.isoformat() if pv.dispensed_at else None,
            "created_at": pv.created_at.isoformat() if pv.created_at else None,
        })

    return APIResponse(status="ok", message="وصفاتك", data={"prescriptions": items}, ref=ref)


@router.get("/my/deliveries")
@limiter.limit("30/minute")
async def my_deliveries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    ref = new_ref()
    presc_ids = (await db.execute(
        select(Prescription.id).where(Prescription.patient_id == user.id)
    )).scalars().all()
    if not presc_ids:
        return APIResponse(status="ok", message="قائمة توصيلاتك", data={"deliveries": []}, ref=ref)
    tickets = (await db.execute(
        select(DeliveryTicket).where(DeliveryTicket.prescription_id.in_(presc_ids))
    )).scalars().all()
    deliveries_map = {}
    if presc_ids:
        deliveries = (await db.execute(
            select(Delivery).where(Delivery.prescription_id.in_([str(pid) for pid in presc_ids]))
        )).scalars().all()
        for d in deliveries:
            deliveries_map[str(d.prescription_id)] = str(d.id)
    return APIResponse(status="ok", message="قائمة توصيلاتك", data={
        "deliveries": [
            {
                "ticket_id": str(t.id),
                "status": "delivered" if t.is_fulfilled else "in_transit",
                "delivery_id": deliveries_map.get(str(t.prescription_id)),
            }
            for t in tickets
        ]
    }, ref=ref)
