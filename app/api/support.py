import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.support_ticket import SupportTicket, TicketMessage
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


class CreateTicketRequest(BaseModel):
    subject: str
    message: str
    category: str = "general"
    priority: str = "normal"


class AddMessageRequest(BaseModel):
    message: str


class UpdateStatusRequest(BaseModel):
    status: str


@router.post("")
@limiter.limit("5/minute")
async def create_ticket(
    body: CreateTicketRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    ref = new_ref()
    ticket = SupportTicket(
        user_id=user.id,
        subject=body.subject,
        message=body.message,
        category=body.category,
        priority=body.priority,
    )
    db.add(ticket)
    await db.commit()
    logger.info("support.ticket_created", ticket_id=ticket.id, user_id=user.id, subject=body.subject, ref=ref)
    return APIResponse(status="ok", message="Support ticket created", data={"id": ticket.id}, ref=ref)


@router.get("")
@limiter.limit("30/minute")
async def list_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    ref = new_ref()
    query = select(SupportTicket)
    if user.role not in (Role.ADMIN, Role.SUPER_ADMIN):
        query = query.where(SupportTicket.user_id == user.id)
    if status:
        query = query.where(SupportTicket.status == status)
    query = query.order_by(SupportTicket.created_at.desc())

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    offset = (page - 1) * per_page
    rows = (await db.execute(query.offset(offset).limit(per_page))).scalars().all()

    return APIResponse(status="ok", message="Tickets", data={
        "tickets": [
            {
                "id": str(t.id),
                "subject": t.subject,
                "category": t.category,
                "priority": t.priority,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }, ref=ref)


@router.get("/{ticket_id}")
@limiter.limit("30/minute")
async def get_ticket(
    request: Request,
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    ref = new_ref()
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if user.role not in (Role.ADMIN, Role.SUPER_ADMIN) and ticket.user_id != user.id:
        raise HTTPException(403, "Access denied")

    messages = (await db.execute(
        select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
    )).scalars().all()

    return APIResponse(status="ok", message="Ticket details", data={
        "id": str(ticket.id),
        "subject": ticket.subject,
        "message": ticket.message,
        "category": ticket.category,
        "priority": ticket.priority,
        "status": ticket.status,
        "messages": [
            {
                "id": str(m.id),
                "author_id": m.author_id,
                "message": m.message,
                "is_internal": m.is_internal,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
    }, ref=ref)


@router.post("/{ticket_id}/messages")
@limiter.limit("10/minute")
async def add_ticket_message(
    ticket_id: str, body: AddMessageRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    ref = new_ref()
    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if user.role not in (Role.ADMIN, Role.SUPER_ADMIN) and ticket.user_id != user.id:
        raise HTTPException(403, "Access denied")
    if ticket.status == "closed":
        raise HTTPException(400, "Ticket is closed")

    msg = TicketMessage(
        ticket_id=ticket_id,
        author_id=user.id,
        message=body.message,
    )
    db.add(msg)
    ticket.status = "in_progress" if ticket.status == "open" else ticket.status
    ticket.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return APIResponse(status="ok", message="Message added", data={"id": msg.id}, ref=ref)


@router.patch("/{ticket_id}/status")
@limiter.limit("10/minute")
async def update_ticket_status(
    ticket_id: str, body: UpdateStatusRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN, Role.SUPER_ADMIN)),
):
    ref = new_ref()
    new_status = body.status
    valid = {"open", "in_progress", "resolved", "closed"}
    if new_status not in valid:
        raise HTTPException(400, f"Invalid status. Choose: {', '.join(valid)}")

    ticket = await db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    ticket.status = new_status
    ticket.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return APIResponse(status="ok", message=f"Status updated to {new_status}", ref=ref)



