import structlog
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.delivery import DeliveryTicket, VettedDriver, Delivery
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


class FulfillBody(BaseModel):
    otp: str


@router.get("/tickets")
@limiter.limit("30/minute")
async def driver_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    ref = new_ref()
    vetted = (await db.execute(
        select(VettedDriver.driver_token_hash).where(VettedDriver.user_id == user.id)
    )).scalars().all()

    if not vetted:
        return APIResponse(status="ok", message="تذاكر التوصيل", data={"tickets": []}, ref=ref)

    tickets = (await db.execute(
        select(DeliveryTicket).where(
            DeliveryTicket.driver_token_hash.in_(vetted),
            DeliveryTicket.is_fulfilled == False,
        )
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


@router.post("/tickets/{ticket_id}/fulfill")
@limiter.limit("20/minute")
async def fulfill_ticket(
    ticket_id: str,
    body: FulfillBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    ref = new_ref()
    try:
        import uuid
        tid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(400, "Invalid ticket ID")

    vetted = (await db.execute(
        select(VettedDriver.driver_token_hash).where(VettedDriver.user_id == user.id)
    )).scalars().all()
    if not vetted:
        raise HTTPException(403, "No vetted driver profile linked to this account")

    ticket = await db.get(DeliveryTicket, tid)
    if not ticket:
        raise HTTPException(404, "Delivery ticket not found")
    if ticket.driver_token_hash not in vetted:
        raise HTTPException(403, "This ticket is not assigned to you")
    if ticket.is_fulfilled:
        raise HTTPException(409, "Ticket already fulfilled")

    import hashlib
    if hashlib.sha256(body.otp.encode()).hexdigest() != ticket.otp_hash:
        ticket.failed_otp_attempts = (ticket.failed_otp_attempts or 0) + 1
        if ticket.failed_otp_attempts >= 5:
            ticket.locked_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(403, "Invalid OTP")
    if ticket.locked_at:
        raise HTTPException(423, "Ticket is locked due to too many failed attempts")
    if ticket.expires_at and ticket.expires_at < datetime.utcnow():
        raise HTTPException(410, "Ticket has expired")

    ticket.is_fulfilled = True
    ticket.fulfilled_at = datetime.utcnow()
    ticket.encrypted_dropoff = None

    from app.models.billing import DeliveryCommission, DriverPayout, DriverPayoutStatus
    from decimal import Decimal

    commission = DeliveryCommission(
        delivery_ticket_id=tid,
        commission_amount_tnd=Decimal("3.00"),
    )
    db.add(commission)

    payout = DriverPayout(
        driver_token_hash=ticket.driver_token_hash,
        delivery_ticket_id=tid,
        amount_tnd=Decimal("3.00"),
        status=DriverPayoutStatus.PAID,
        paid_at=datetime.utcnow(),
    )
    db.add(payout)

    await db.commit()
    logger.info("ticket.fulfilled.web", ref=ref, ticket=str(tid))

    return APIResponse(status="ok", message="Livraison confirmée", ref=ref)
