import structlog
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.medication import PharmacyMedication
from app.models.analytics_event import AnalyticsEvent
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/alerts")
@limiter.limit("20/minute")
async def inventory_alerts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    ref = new_ref()
    from app.models.user import User
    pharmacist_user = (await db.execute(
        select(User).where(User.identity_id == user.id)
    )).scalar_one_or_none()
    pharmacy_id_val = pharmacist_user.pharmacy_id if pharmacist_user else user.id
    low_stock = await db.execute(
        select(PharmacyMedication).where(
            PharmacyMedication.pharmacy_id == pharmacy_id_val,
            PharmacyMedication.stock_quantity < 10,
            PharmacyMedication.is_available == True,
        ).order_by(PharmacyMedication.stock_quantity)
    )
    out_of_stock = await db.execute(
        select(PharmacyMedication).where(
            PharmacyMedication.pharmacy_id == pharmacy_id_val,
            PharmacyMedication.stock_quantity == 0,
            PharmacyMedication.is_available == True,
        ).order_by(PharmacyMedication.medication_name)
    )

    return APIResponse(status="ok", message="Inventory alerts", data={
        "low_stock": [
            {
                "id": str(m.id),
                "medication_name": m.medication_name,
                "dosage": m.dosage,
                "stock_quantity": m.stock_quantity,
            }
            for m in low_stock.scalars().all()
        ],
        "out_of_stock": [
            {
                "id": str(m.id),
                "medication_name": m.medication_name,
                "dosage": m.dosage,
            }
            for m in out_of_stock.scalars().all()
        ],
        "total_alerts": 0,
    }, ref=ref)


@router.get("/predictions")
@limiter.limit("10/minute")
async def inventory_predictions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
    days: int = Query(30, ge=7, le=90),
):
    ref = new_ref()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    events = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.pharmacy_id == user.id,
            AnalyticsEvent.event_type == "prescription_dispensed",
            AnalyticsEvent.created_at >= start,
        )
    )
    rows = events.scalars().all()
    medication_counts: dict[str, int] = {}
    for e in rows:
        meta = e.metadata_json or {}
        name = meta.get("medication_name", "unknown")
        medication_counts[name] = medication_counts.get(name, 0) + 1

    predictions = []
    for name, count in sorted(medication_counts.items(), key=lambda x: -x[1]):
        daily_rate = count / max(days, 1)
        predictions.append({
            "medication_name": name,
            "dispensed_last_30d": count,
            "daily_rate": round(daily_rate, 2),
            "predicted_next_30d": round(daily_rate * 30),
        })

    return APIResponse(status="ok", message="Inventory predictions", data={
        "predictions": predictions[:20],
        "total_medications_analyzed": len(medication_counts),
    }, ref=ref)
