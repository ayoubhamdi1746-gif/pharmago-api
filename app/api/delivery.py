import uuid, structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.limiter import limiter
from app.schemas.common import APIResponse, DeliveryAssignRequest, DeliveryFulfillRequest
from app.services.blind_assignment import BlindAssignmentEngine
from app.config import settings
from app.logging.cfg import new_ref

router = APIRouter()
logger = structlog.get_logger()


@router.post("/assign/{prescription_id}", status_code=201)
async def delivery_assign(
    prescription_id: uuid.UUID, body: DeliveryAssignRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST, Role.ADMIN)),
):
    ref = new_ref()
    engine = BlindAssignmentEngine(db, settings.FERNET_KEY.encode())
    ticket = await engine.assign(
        prescription_id, body.pickup_coords, body.encrypted_dropoff, ref=ref,
    )
    return APIResponse(status="ok", message="تم تعيين موصّل", data={
        "ticket_id": str(ticket.id),
        "pickup_coords": ticket.pickup_coords,
        "otp": getattr(ticket, "_plain_otp", ""),
    }, ref=ref)


@router.post("/fulfill/{ticket_id}")
@limiter.limit(settings.FULFILL_RATE_LIMIT)
async def delivery_fulfill(
    ticket_id: uuid.UUID, body: DeliveryFulfillRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    ref = new_ref()
    engine = BlindAssignmentEngine(db, settings.FERNET_KEY.encode())
    await engine.fulfill(ticket_id, body.otp, driver_token=user.id, ref=ref)
    return APIResponse(status="ok", message="تم التسليم بنجاح", data=None, ref=ref)
