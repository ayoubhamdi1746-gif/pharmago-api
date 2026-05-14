import uuid, structlog
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.user import User
from app.models.billing import PharmacySubscription, DeliveryCommission
from app.models.delivery import DeliveryTicket
from app.logging.cfg import new_ref

router = APIRouter()
logger = structlog.get_logger()


@router.get("/super/stats")
async def super_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()

    total_pharmacies = await db.execute(
        select(func.count(PharmacySubscription.id))
    )
    total_pharmacies = total_pharmacies.scalar()

    total_patients = await db.execute(
        select(func.count(User.id)).where(User.role == "patient")
    )
    total_patients = total_patients.scalar()

    total_deliveries = await db.execute(
        select(func.count(DeliveryTicket.id)).where(DeliveryTicket.is_fulfilled == True)
    )
    total_deliveries = total_deliveries.scalar()

    total_revenue = await db.execute(
        select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
    )
    total_revenue = float(total_revenue.scalar())

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    new_users = await db.execute(
        select(func.count(User.id)).where(User.created_at >= seven_days_ago)
    )
    new_users = new_users.scalar()

    return APIResponse(status="ok", message="Super admin stats", data={
        "total_pharmacies": total_pharmacies,
        "total_patients": total_patients,
        "total_deliveries": total_deliveries,
        "total_revenue": total_revenue,
        "new_users_last_7_days": new_users,
    }, ref=ref)


@router.get("/super/users")
async def super_list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    ref = new_ref()

    total = await db.execute(select(func.count(User.id)))
    total = total.scalar()

    offset = (page - 1) * per_page
    rows = (await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )).scalars().all()

    return APIResponse(status="ok", message="User list", data={
        "users": [
            {
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if hasattr(u, "created_at") and u.created_at else None,
                "full_name": getattr(u, "full_name", None),
            }
            for u in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }, ref=ref)


@router.patch("/super/users/{user_id}/role")
async def super_update_role(
    user_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    body = await request.json()
    new_role = body.get("role", "").lower()

    valid_roles = {"patient", "pharmacist", "doctor", "driver", "admin", "super_admin"}
    if new_role not in valid_roles:
        from app.exceptions.handlers import ValidationException
        raise ValidationException(f"Invalid role: {new_role}", ref)

    target = await db.get(User, str(user_id))
    if not target:
        from app.exceptions.handlers import NotFoundException
        raise NotFoundException("User not found", ref)

    target.role = new_role
    await db.commit()
    await db.refresh(target)

    return APIResponse(status="ok", message=f"Role updated to {new_role}", data={
        "id": str(target.id),
        "username": target.username,
        "role": target.role,
    }, ref=ref)


@router.delete("/super/users/{user_id}")
async def super_delete_user(
    user_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    target = await db.get(User, str(user_id))
    if not target:
        from app.exceptions.handlers import NotFoundException
        raise NotFoundException("User not found", ref)

    target.is_active = False
    await db.commit()
    await db.refresh(target)

    return APIResponse(status="ok", message="User deactivated (soft delete)", data={
        "id": str(target.id),
        "username": target.username,
        "is_active": target.is_active,
    }, ref=ref)
