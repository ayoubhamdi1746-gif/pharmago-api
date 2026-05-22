import uuid, structlog
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.user import User
from app.models.billing import PharmacySubscription, DeliveryCommission, DriverPayout
from app.models.delivery import DeliveryTicket
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/stats")
@limiter.limit("30/minute")
async def super_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()

    try:
        total_pharmacies = await db.execute(select(func.count(PharmacySubscription.id)))
        total_pharmacies = total_pharmacies.scalar() or 0
    except Exception:
        total_pharmacies = 0

    try:
        total_patients = await db.execute(
            select(func.count(User.id)).where(User.role == "patient")
        )
        total_patients = total_patients.scalar() or 0
    except Exception:
        total_patients = 0

    try:
        total_deliveries = await db.execute(
            select(func.count(DeliveryTicket.id)).where(DeliveryTicket.is_fulfilled == True)
        )
        total_deliveries = total_deliveries.scalar() or 0
    except Exception:
        total_deliveries = 0

    try:
        total_revenue = await db.execute(
            select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
        )
        total_revenue = float(total_revenue.scalar() or 0)
    except Exception:
        total_revenue = 0.0

    try:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        new_users = await db.execute(
            select(func.count(User.id)).where(User.created_at >= seven_days_ago)
        )
        new_users = new_users.scalar() or 0
    except Exception:
        new_users = 0

    # Calculate percentage changes from previous period (14-7 days ago)
    try:
        prev_pharmacies = await db.execute(
            select(func.count(PharmacySubscription.id)).where(PharmacySubscription.started_at < seven_days_ago)
        )
        prev_pharmacies = prev_pharmacies.scalar() or 1
        pharmacies_change_pct = round(((total_pharmacies - prev_pharmacies) / prev_pharmacies) * 100, 1)
    except Exception:
        pharmacies_change_pct = 0.0

    try:
        fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
        prev_patients = await db.execute(
            select(func.count(User.id)).where(User.role == "patient", User.created_at < seven_days_ago)
        )
        prev_patients = prev_patients.scalar() or 1
        patients_change_pct = round(((total_patients - prev_patients) / prev_patients) * 100, 1)
    except Exception:
        patients_change_pct = 0.0

    try:
        prev_deliveries = await db.execute(
            select(func.count(DeliveryTicket.id)).where(DeliveryTicket.is_fulfilled == True, DeliveryTicket.created_at < seven_days_ago)
        )
        prev_deliveries = prev_deliveries.scalar() or 1
        deliveries_change_pct = round(((total_deliveries - prev_deliveries) / prev_deliveries) * 100, 1)
    except Exception:
        deliveries_change_pct = 0.0

    try:
        prev_revenue = await db.execute(
            select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
            .where(DeliveryCommission.created_at < seven_days_ago)
        )
        prev_revenue = float(prev_revenue.scalar() or 1)
        revenue_change_pct = round(((total_revenue - prev_revenue) / prev_revenue) * 100, 1)
    except Exception:
        revenue_change_pct = 0.0

    return APIResponse(status="ok", message="Super admin stats", data={
        "total_pharmacies": total_pharmacies,
        "total_patients": total_patients,
        "total_deliveries": total_deliveries,
        "total_revenue": total_revenue,
        "new_users_last_7_days": new_users,
        "pharmacies_change_pct": pharmacies_change_pct,
        "patients_change_pct": patients_change_pct,
        "deliveries_change_pct": deliveries_change_pct,
        "revenue_change_pct": revenue_change_pct,
    }, ref=ref)


@router.get("/users")
@limiter.limit("30/minute")
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


class UpdateUserRoleRequest(BaseModel):
    role: str


@router.patch("/users/{user_id}/role")
@limiter.limit("10/minute")
async def super_update_role(
    user_id: uuid.UUID, body: UpdateUserRoleRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    new_role = body.role.lower()

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


@router.patch("/users/{user_id}/toggle")
@limiter.limit("10/minute")
async def super_toggle_user(
    user_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    target = await db.get(User, str(user_id))
    if not target:
        from app.exceptions.handlers import NotFoundException
        raise NotFoundException("User not found", ref)

    target.is_active = not target.is_active
    await db.commit()

    status_text = "activated" if target.is_active else "deactivated"
    return APIResponse(status="ok", message=f"User {status_text}", data={
        "id": str(target.id),
        "username": target.username,
        "is_active": target.is_active,
    }, ref=ref)


@router.delete("/users/{user_id}")
@limiter.limit("10/minute")
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


@router.get("/stats/monthly")
@limiter.limit("30/minute")
async def super_monthly_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    now = datetime.utcnow()
    months_data = []

    for i in range(5, -1, -1):
        month = now.month - i
        year = now.year
        while month < 1:
            month += 12
            year -= 1

        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        if month == 12:
            month_end = now.replace(year=year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            month_end = now.replace(year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

        month_name = month_start.strftime("%b")

        try:
            revenue = await db.execute(
                select(func.coalesce(func.sum(PharmacySubscription.price_tnd), 0))
                .where(PharmacySubscription.is_active == True)
            )
            rev = float(revenue.scalar() or 0)
        except Exception:
            rev = 0

        try:
            count_result = await db.execute(
                select(func.count(User.id))
                .where(User.created_at >= month_start, User.created_at < month_end)
            )
            cnt = count_result.scalar() or 0
        except Exception:
            cnt = 0

        months_data.append({"month": month_name, "revenue": rev, "count": cnt})

    return APIResponse(status="ok", message="Monthly stats", data={"months": months_data}, ref=ref)


@router.get("/stats/daily")
@limiter.limit("30/minute")
async def super_daily_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    days_data = []
    for i in range(6, -1, -1):
        day_date = datetime.utcnow() - timedelta(days=i)
        day_name = day_date.strftime("%a")
        try:
            day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            signups = (await db.execute(
                select(func.count(User.id)).where(User.created_at >= day_start, User.created_at < day_end)
            )).scalar() or 0
            revenue = (await db.execute(
                select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
                .where(DeliveryTicket.is_fulfilled == True)
            )).scalar() or 0
        except Exception:
            signups = 0
            revenue = 0
        days_data.append({"day": day_name, "signups": int(signups), "revenue": float(revenue)})

    return APIResponse(status="ok", message="Daily stats", data={"days": days_data}, ref=ref)


@router.get("/activity")
@limiter.limit("30/minute")
async def super_activity(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    ref = new_ref()
    events = []

    try:
        new_users = (await db.execute(
            select(User).order_by(User.created_at.desc()).limit(5)
        )).scalars().all()
        for u in new_users:
            if u.created_at:
                events.append({
                    "type": "user",
                    "description": f"Nouveau {u.role or 'utilisateur'} : {u.username}",
                    "created_at": u.created_at.isoformat(),
                })
    except Exception:
        pass

    try:
        subs = (await db.execute(
            select(PharmacySubscription).order_by(PharmacySubscription.started_at.desc()).limit(3)
        )).scalars().all()
        for s in subs:
            if s.started_at:
                events.append({
                    "type": "pharmacy",
                    "description": f"Pharmacie '{s.pharmacy_name}' inscrite ({s.plan.value})",
                    "created_at": s.started_at.isoformat(),
                })
    except Exception:
        pass

    try:
        payouts = (await db.execute(
            select(DriverPayout).order_by(DriverPayout.created_at.desc()).limit(3)
        )).scalars().all()
        for p in payouts:
            if p.created_at:
                events.append({
                    "type": "payment",
                    "description": f"Paiement {float(p.amount_tnd):.2f} TND",
                    "created_at": p.created_at.isoformat(),
                })
    except Exception:
        pass

    events.sort(key=lambda x: x["created_at"], reverse=True)

    return APIResponse(status="ok", message="Activity feed", data={"events": events[:10]}, ref=ref)
