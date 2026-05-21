import structlog
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.analytics_event import AnalyticsEvent
from app.models.delivery import Delivery, DeliveryTicket
from app.models.billing import PharmacySubscription, DeliveryCommission
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.medication import PharmacyMedication
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/dashboard")
@limiter.limit("20/minute")
async def pharmacy_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    from app.models.user import User
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    pharmacy_id_val = pharmacist_user.pharmacy_id if pharmacist_user else user.id

    deliveries_today = await db.execute(
        select(func.count(DeliveryTicket.id)).where(
            DeliveryTicket.is_fulfilled == True,
            DeliveryTicket.created_at >= today_start,
        ).select_from(DeliveryTicket).join(Prescription, DeliveryTicket.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharmacy_id_val
        )
    )
    deliveries_this_month = await db.execute(
        select(func.count(DeliveryTicket.id)).where(
            DeliveryTicket.is_fulfilled == True,
            DeliveryTicket.created_at >= month_start,
        ).select_from(DeliveryTicket).join(Prescription, DeliveryTicket.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharmacy_id_val
        )
    )
    prescriptions_pending = await db.execute(
        select(func.count(PrescriptionVerification.id)).where(
            PrescriptionVerification.status == "PENDING"
        ).select_from(PrescriptionVerification).join(Prescription, PrescriptionVerification.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharmacy_id_val
        )
    )
    low_stock = await db.execute(
        select(func.count(PharmacyMedication.id)).where(
            PharmacyMedication.stock_quantity < 10,
            PharmacyMedication.is_available == True,
            PharmacyMedication.pharmacy_id == pharmacy_id_val,
        )
    )
    revenue_month = await db.execute(
        select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0)).where(
            DeliveryCommission.created_at >= month_start
        ).select_from(DeliveryCommission).join(DeliveryTicket, DeliveryCommission.delivery_ticket_id == DeliveryTicket.id).join(Prescription, DeliveryTicket.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharmacy_id_val
        )
    )

    return APIResponse(status="ok", message="Dashboard", data={
        "deliveries_today": deliveries_today.scalar() or 0,
        "deliveries_this_month": deliveries_this_month.scalar() or 0,
        "prescriptions_pending": prescriptions_pending.scalar() or 0,
        "low_stock_items": low_stock.scalar() or 0,
        "revenue_this_month": float(revenue_month.scalar() or 0),
    }, ref=ref)


@router.get("/analytics/revenue")
@limiter.limit("20/minute")
async def revenue_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST, Role.ADMIN)),
    days: int = Query(30, ge=7, le=365),
):
    ref = new_ref()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    events = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.pharmacy_id == user.id,
            AnalyticsEvent.event_type == "revenue",
            AnalyticsEvent.created_at >= start,
            AnalyticsEvent.created_at <= end,
        ).order_by(AnalyticsEvent.created_at)
    )
    rows = events.scalars().all()
    daily = {}
    for r in rows:
        day = r.created_at.strftime("%Y-%m-%d")
        daily[day] = daily.get(day, 0) + (r.value or 0)

    return APIResponse(status="ok", message="Revenue analytics", data={
        "daily_revenue": [{"date": d, "amount": v} for d, v in sorted(daily.items())],
        "total": sum(daily.values()),
        "average_per_day": sum(daily.values()) / max(len(daily), 1),
    }, ref=ref)


@router.get("/analytics/deliveries")
@limiter.limit("20/minute")
async def delivery_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST, Role.ADMIN)),
    days: int = Query(30, ge=7, le=365),
):
    ref = new_ref()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    from app.models.user import User
    pharm_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    pharm_id = pharm_user.pharmacy_id if pharm_user else user.id
    tickets = await db.execute(
        select(DeliveryTicket).where(
            DeliveryTicket.created_at >= start,
            DeliveryTicket.created_at <= end,
        ).select_from(DeliveryTicket).join(Prescription, DeliveryTicket.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharm_id
        ).order_by(DeliveryTicket.created_at)
    )
    rows = tickets.scalars().all()
    daily = {}
    for t in rows:
        day = t.created_at.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"total": 0, "fulfilled": 0}
        daily[day]["total"] += 1
        if t.is_fulfilled:
            daily[day]["fulfilled"] += 1

    return APIResponse(status="ok", message="Delivery analytics", data={
        "daily": [{"date": d, **v} for d, v in sorted(daily.items())],
        "total": len(rows),
        "fulfilled": sum(1 for t in rows if t.is_fulfilled),
        "fulfillment_rate": round(sum(1 for t in rows if t.is_fulfilled) / max(len(rows), 1) * 100, 1),
    }, ref=ref)


@router.get("/analytics/prescriptions")
@limiter.limit("20/minute")
async def prescription_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST, Role.ADMIN)),
    days: int = Query(30, ge=7, le=365),
):
    ref = new_ref()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    from app.models.user import User
    pharm_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    pharm_id = pharm_user.pharmacy_id if pharm_user else user.id
    verifications = await db.execute(
        select(PrescriptionVerification).where(
            PrescriptionVerification.created_at >= start,
            PrescriptionVerification.created_at <= end,
        ).select_from(PrescriptionVerification).join(Prescription, PrescriptionVerification.prescription_id == Prescription.id).where(
            Prescription.pharmacy_id == pharm_id
        ).order_by(PrescriptionVerification.created_at)
    )
    rows = verifications.scalars().all()
    by_status = {}
    for v in rows:
        by_status[v.status] = by_status.get(v.status, 0) + 1

    return APIResponse(status="ok", message="Prescription analytics", data={
        "by_status": by_status,
        "total": len(rows),
        "verified": by_status.get("VERIFIED", 0),
        "rejected": by_status.get("REJECTED", 0),
        "pending": by_status.get("PENDING", 0) + by_status.get("HIGH_RISK_PENDING", 0),
    }, ref=ref)
