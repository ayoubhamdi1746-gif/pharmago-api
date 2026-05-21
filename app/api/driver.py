import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.delivery import DeliveryTicket
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/tickets")
@limiter.limit("30/minute")
async def driver_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    ref = new_ref()
    tickets = (await db.execute(
        select(DeliveryTicket).where(DeliveryTicket.driver_token_hash == user.id)
    )).scalars().all()

    return APIResponse(status="ok", message="تذاكر التوصيل", data={
        "tickets": [{
            "id": str(t.id),
            "prescription_id": str(t.prescription_id),
            "pickup_coords": t.pickup_coords,
            "is_fulfilled": t.is_fulfilled,
            "expires_at": t.expires_at.isoformat(),
            "status": "delivered" if t.is_fulfilled else "assigned",
        } for t in tickets]
    }, ref=ref)
