import uuid, structlog
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse, PharmacistVerifyRequest, PharmacistAddMedicationRequest, PharmacistUpdateMedicationRequest
from app.models.user import User
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import ControlledSubstance, LethalRiskSubstance
from app.models.medication import PharmacyMedication
from app.models.billing import DeliveryCommission, CommissionStatus, PharmacySubscription, SubscriptionPlan, PLAN_PRICES, PLAN_LIMITS
from app.models.payment import PaymentTransaction
from app.models.delivery import DeliveryTicket
from app.services.verification_gate import verify_prescription
from app.exceptions.handlers import NotFoundException, ForbiddenException
from app.logging.cfg import new_ref

router = APIRouter()
logger = structlog.get_logger()


def _resolve_drug_name(dpm_code: str, controlled_map: dict, lethal_map: dict) -> str:
    if dpm_code in controlled_map:
        return controlled_map[dpm_code]
    if dpm_code in lethal_map:
        return lethal_map[dpm_code]
    return dpm_code


@router.get("/queue")
async def pharmacist_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    if not pharmacist_user or not pharmacist_user.pharmacy_id:
        raise ForbiddenException("Pharmacy profile not found", ref)
    pharmacy_id = pharmacist_user.pharmacy_id

    query = select(PrescriptionVerification)
    subq = select(Prescription.id).where(Prescription.pharmacy_id == pharmacy_id)
    query = query.where(PrescriptionVerification.prescription_id.in_(subq))
    rows = (await db.execute(query)).scalars().all()

    presc_ids = [pv.prescription_id for pv in rows]
    presc_rows = (await db.execute(
        select(Prescription).where(Prescription.id.in_(presc_ids))
    )).scalars().all()
    presc_map = {p.id: p for p in presc_rows}

    controlled_rows = (await db.execute(select(ControlledSubstance))).scalars().all()
    controlled_map = {s.dpm_code: s.generic_name for s in controlled_rows}
    lethal_rows = (await db.execute(select(LethalRiskSubstance))).scalars().all()
    lethal_map = {s.dpm_code: s.generic_name for s in lethal_rows}

    dcr_rows = (await db.execute(
        select(DoctorConfirmationRequest)
    )).scalars().all()
    dcr_map = {r.prescription_id: r for r in dcr_rows}

    items = []
    for pv in rows:
        presc = presc_map.get(pv.prescription_id)
        medicament = ""
        dosage = ""
        all_items = []
        if presc and presc.items:
            raw = presc.items if isinstance(presc.items, list) else []
            for it in raw:
                code = it.get("dpm_code", "")
                name = _resolve_drug_name(code, controlled_map, lethal_map)
                dose = it.get("dose_mg", 0)
                unit = it.get("unit", "mg")
                qty = it.get("quantity", 0)
                all_items.append({
                    "dpm_code": code,
                    "medicament": name,
                    "dose_mg": dose,
                    "unit": unit,
                    "quantity": qty,
                })
            first = raw[0] if raw else {}
            code = first.get("dpm_code", "")
            medicament = _resolve_drug_name(code, controlled_map, lethal_map)
            dose = first.get("dose_mg", 0)
            unit = first.get("unit", "mg")
            dosage = f"{dose} {unit}" if dose else ""

        dcr = dcr_map.get(pv.prescription_id)
        items.append({
            "prescription_id": str(pv.prescription_id),
            "status": pv.status,
            "medicament": medicament,
            "dosage": dosage,
            "items": all_items,
            "doctor_name": presc.doctor_name if presc else None,
            "doctor_phone": presc.doctor_phone if presc else None,
            "doctor_email": presc.doctor_email if presc else None,
            "patient_reference_token": presc.patient_reference_token if presc else None,
            "pharmacist_id": str(pv.pharmacist_id) if pv.pharmacist_id else None,
            "pharmacist_license_hash": pv.pharmacist_license_hash,
            "verified_at": pv.verified_at.isoformat() if pv.verified_at else None,
            "dispensed_at": pv.dispensed_at.isoformat() if pv.dispensed_at else None,
            "created_at": pv.created_at.isoformat() if pv.created_at else None,
            "doctor_confirmation_status": dcr.status if dcr else None,
            "doctor_confirmation_expires_at": dcr.expires_at.isoformat() if dcr and dcr.expires_at else None,
        })
    return APIResponse(status="ok", message="قائمة الوصفات", data={"prescriptions": items}, ref=ref)


@router.post("/verify/{prescription_id}")
async def pharmacist_verify(
    prescription_id: uuid.UUID, body: PharmacistVerifyRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pv = await verify_prescription(db, prescription_id, user.id, doctor_signed_token=body.doctor_signed_token, ref=ref)
    return APIResponse(status="ok", message="تم التحقق من الوصفة", data={"status": pv.status}, ref=ref)


@router.post("/dispense/{prescription_id}")
async def pharmacist_dispense(
    prescription_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pv = (await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.prescription_id == prescription_id)
    )).scalar_one_or_none()
    if not pv:
        raise NotFoundException("Prescription not found", ref)
    if pv.status != "VERIFIED":
        raise ForbiddenException("Only VERIFIED prescriptions can be dispensed", ref)
    pv.status = "DISPENSED"
    await db.commit()
    return APIResponse(status="ok", message="تم تجهيز الدواء", data={"status": "DISPENSED"}, ref=ref)


@router.get("/inventory")
async def pharmacist_list_inventory(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    if not pharmacist_user or not pharmacist_user.pharmacy_id:
        raise ForbiddenException("Pharmacy profile not found", ref)
    medications = (await db.execute(
        select(PharmacyMedication).where(
            PharmacyMedication.pharmacy_id == uuid.UUID(pharmacist_user.pharmacy_id)
        ).order_by(PharmacyMedication.medication_name)
    )).scalars().all()
    return APIResponse(status="ok", message="قائمة الأدوية", data={
        "medications": [
            {
                "id": str(m.id),
                "pharmacy_id": str(m.pharmacy_id),
                "medication_name": m.medication_name,
                "dosage": m.dosage,
                "stock_quantity": m.stock_quantity,
                "is_available": m.is_available,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in medications
        ],
    }, ref=ref)


@router.post("/inventory", status_code=201)
async def pharmacist_add_medication(
    body: PharmacistAddMedicationRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    medication = PharmacyMedication(
        pharmacy_id=uuid.UUID(body.pharmacy_id),
        medication_name=body.medication_name,
        dosage=body.dosage,
        stock_quantity=body.stock_quantity,
        is_available=body.is_available,
    )
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return APIResponse(status="ok", message="تم إضافة الدواء", data={
        "id": str(medication.id),
        "medication_name": medication.medication_name,
        "dosage": medication.dosage,
        "stock_quantity": medication.stock_quantity,
    }, ref=ref)


@router.patch("/inventory/{medication_id}")
async def pharmacist_update_medication(
    medication_id: uuid.UUID, body: PharmacistUpdateMedicationRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    medication = await db.get(PharmacyMedication, medication_id)
    if not medication:
        raise NotFoundException("Medication not found", ref)
    if body.medication_name is not None:
        medication.medication_name = body.medication_name
    if body.dosage is not None:
        medication.dosage = body.dosage
    if body.stock_quantity is not None:
        medication.stock_quantity = body.stock_quantity
    if body.is_available is not None:
        medication.is_available = body.is_available
    medication.updated_at = datetime.utcnow()
    await db.commit()
    return APIResponse(status="ok", message="تم تحديث الدواء", data={
        "id": str(medication.id),
        "medication_name": medication.medication_name,
        "dosage": medication.dosage,
        "stock_quantity": medication.stock_quantity,
        "is_available": medication.is_available,
    }, ref=ref)


@router.get("/revenue")
async def pharmacist_revenue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()

    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    if not pharmacist_user or not pharmacist_user.pharmacy_id:
        raise ForbiddenException("Pharmacy profile not found", ref)
    pharmacy_id_str = pharmacist_user.pharmacy_id

    sub = (await db.execute(
        select(PharmacySubscription).where(
            PharmacySubscription.pharmacy_id == uuid.UUID(pharmacy_id_str)
        )
    )).scalar_one_or_none()
    total_pharmacy_earnings = float(sub.total_delivery_earnings) if sub else 0.0

    ticket_count = await db.scalar(
        select(func.count(DeliveryTicket.id))
        .where(DeliveryTicket.prescription_id.in_(
            select(Prescription.id).where(Prescription.pharmacy_id == uuid.UUID(pharmacy_id_str))
        ))
    )
    deliveries_this_month = ticket_count or 0

    six_months_ago = datetime.utcnow() - timedelta(days=180)
    monthly_rows = (await db.execute(
        select(DeliveryCommission)
        .where(DeliveryCommission.created_at >= six_months_ago)
    )).scalars().all()

    total_commissions = sum(c.commission_amount_tnd for c in monthly_rows)
    pending_commissions = sum(
        c.commission_amount_tnd for c in monthly_rows if c.status == CommissionStatus.PENDING
    )

    revenue_history: list[dict] = []
    for i in range(5, -1, -1):
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30 * i)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        month_name = month_start.strftime("%Y-%m")

        month_comms = [
            c for c in monthly_rows
            if month_start <= c.created_at <= month_end
        ]
        comms = sum(c.commission_amount_tnd for c in month_comms)
        revenue_history.append({
            "month": month_name,
            "commissions": float(comms),
            "pharmacy_earnings": float(comms * Decimal("0.4")),
            "net": float(comms * Decimal("0.6")),
        })

    return APIResponse(status="ok", message="إيرادات الصيدلية", data={
        "total_pharmacy_earnings": float(total_pharmacy_earnings),
        "total_commissions": float(total_commissions),
        "pending_commissions": float(pending_commissions),
        "deliveries_this_month": deliveries_this_month,
        "total_fulfilled_deliveries": deliveries_this_month,
        "revenue_history": revenue_history,
    }, ref=ref)


@router.get("/subscription")
async def pharmacist_subscription(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    if not pharmacist_user or not pharmacist_user.pharmacy_id:
        raise ForbiddenException("Pharmacy profile not found", ref)
    sub = (await db.execute(
        select(PharmacySubscription).where(
            PharmacySubscription.pharmacy_id == uuid.UUID(pharmacist_user.pharmacy_id)
        )
    )).scalar_one_or_none()
    if not sub:
        raise NotFoundException("Subscription not found", ref)
    return APIResponse(status="ok", message="بيانات الاشتراك", data={
        "id": str(sub.id),
        "pharmacy_name": sub.pharmacy_name,
        "pharmacy_id": str(sub.pharmacy_id),
        "city": sub.city,
        "plan": sub.plan.value,
        "price_tnd": float(sub.price_tnd),
        "started_at": sub.started_at.isoformat(),
        "expires_at": sub.expires_at.isoformat(),
        "is_active": sub.is_active,
        "delivery_count_this_month": sub.delivery_count_this_month,
        "delivery_limit": sub.delivery_limit,
        "total_delivery_earnings": float(sub.total_delivery_earnings),
    }, ref=ref)


@router.get("/transactions")
async def pharmacist_transactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    if not pharmacist_user or not pharmacist_user.pharmacy_id:
        raise ForbiddenException("Pharmacy profile not found", ref)
    sub = (await db.execute(
        select(PharmacySubscription).where(
            PharmacySubscription.pharmacy_id == uuid.UUID(pharmacist_user.pharmacy_id)
        )
    )).scalar_one_or_none()
    if not sub:
        raise NotFoundException("Subscription not found", ref)
    txns = (await db.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.subscription_id == sub.id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(3)
    )).scalars().all()
    return APIResponse(status="ok", message="آخر المعاملات", data={
        "transactions": [
            {
                "id": str(t.id),
                "provider": t.provider.value,
                "amount_tnd": float(t.amount_tnd),
                "status": t.status.value,
                "payment_url": t.payment_url,
                "created_at": t.created_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in txns
        ],
    }, ref=ref)
