from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.schemas.common import APIResponse
from app.models.billing import PharmacySubscription
from app.logging.cfg import new_ref

router = APIRouter()


@router.get("/pharmacies")
async def public_pharmacies(db: AsyncSession = Depends(get_db)):
    ref = new_ref()
    rows = (await db.execute(
        select(PharmacySubscription).where(PharmacySubscription.is_active == True)
    )).scalars().all()
    return APIResponse(status="ok", message="قائمة الصيدليات", data={
        "pharmacies": [{
            "id": str(r.id),
            "name": r.pharmacy_name,
            "city": r.city or "",
        } for r in rows]
    }, ref=ref)
