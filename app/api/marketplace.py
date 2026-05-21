import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.medication import PharmacyMedication
from app.models.pharmacy_profile import PharmacyProfile
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/medications")
@limiter.limit("30/minute")
async def search_marketplace(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None),
    pharmacy_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    ref = new_ref()
    query = select(PharmacyMedication).where(PharmacyMedication.is_available == True)
    if pharmacy_id:
        from uuid import UUID
        query = query.where(PharmacyMedication.pharmacy_id == UUID(pharmacy_id))
    if q:
        query = query.where(
            or_(
                PharmacyMedication.medication_name.ilike(f"%{q}%"),
                PharmacyMedication.dosage.ilike(f"%{q}%"),
            )
        )
    total_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_query)).scalar() or 0
    offset = (page - 1) * per_page
    rows = (await db.execute(query.offset(offset).limit(per_page))).scalars().all()

    pharmacy_ids = list(set(str(m.pharmacy_id) for m in rows))
    pharmacy_map = {}
    if pharmacy_ids:
        profiles = await db.execute(
            select(PharmacyProfile).where(PharmacyProfile.user_id.in_(pharmacy_ids))
        )
        for p in profiles.scalars():
            pharmacy_map[p.user_id] = p.pharmacy_name

    return APIResponse(status="ok", message="Marketplace", data={
        "medications": [
            {
                "id": str(m.id),
                "medication_name": m.medication_name,
                "dosage": m.dosage,
                "stock_quantity": m.stock_quantity,
                "pharmacy_id": str(m.pharmacy_id),
                "pharmacy_name": pharmacy_map.get(str(m.pharmacy_id), "Unknown"),
            }
            for m in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }, ref=ref)
