import uuid, hashlib, structlog
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.limiter import limiter
from app.schemas.common import APIResponse, SubscriptionCreate, AdminCreateDriverRequest
from app.models.delivery import VettedDriver, DeliveryTicket
from app.models.abuse import AbuseFlag
from app.models.billing import PharmacySubscription, DeliveryCommission, DriverPayout, DriverPayoutStatus, SubscriptionPlan, PLAN_PRICES, PLAN_LIMITS
from app.exceptions.handlers import NotFoundException, ForbiddenException
from app.logging.cfg import new_ref

router = APIRouter()
logger = structlog.get_logger()


@router.get("/drivers")
async def admin_list_drivers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    drivers = (await db.execute(
        select(VettedDriver).order_by(VettedDriver.license_issued_at.desc())
    )).scalars().all()
    return APIResponse(status="ok", message="Driver list", data={
        "drivers": [
            {
                "driver_token_hash": d.driver_token_hash,
                "issuing_pharmacy_id": str(d.issuing_pharmacy_id),
                "license_issued_at": d.license_issued_at.isoformat(),
                "license_expires_at": d.license_expires_at.isoformat(),
                "is_active": d.is_active,
            }
            for d in drivers
        ],
    }, ref=ref)


@router.get("/stats")
async def admin_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    deliveries_today = (await db.execute(
        select(func.count(DeliveryTicket.id))
        .where(
            DeliveryTicket.is_fulfilled == True,
            DeliveryTicket.created_at >= today_start,
        )
    )).scalar()

    flagged = (await db.execute(
        select(func.count(AbuseFlag.id))
    )).scalar()

    active_drivers = (await db.execute(
        select(func.count(VettedDriver.id))
        .where(VettedDriver.is_active == True)
    )).scalar()

    return APIResponse(status="ok", message="Dashboard stats", data={
        "total_deliveries_today": deliveries_today,
        "flagged_prescriptions": flagged,
        "active_drivers": active_drivers,
    }, ref=ref)


@router.post("/drivers", status_code=201)
@limiter.limit("10/minute")
async def admin_create_driver(
    body: AdminCreateDriverRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    raw_id = body.driver_id or str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_id.encode()).hexdigest()
    driver = VettedDriver(
        driver_token_hash=token_hash,
        issuing_pharmacy_id=uuid.UUID(body.pharmacy_id) if body.pharmacy_id else uuid.uuid4(),
        license_issued_at=datetime.utcnow(),
        license_expires_at=datetime.utcnow() + timedelta(days=90),
        is_active=True,
    )
    db.add(driver)
    await db.commit()
    return APIResponse(status="ok", message="تم تسجيل الموصّل", data={"driver_token_hash": token_hash}, ref=ref)


@router.patch("/drivers/{token_hash}/suspend")
async def admin_suspend_driver(
    token_hash: str, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    driver = (await db.execute(
        select(VettedDriver).where(VettedDriver.driver_token_hash == token_hash)
    )).scalar_one_or_none()
    if not driver:
        raise NotFoundException("Driver not found", ref)
    driver.is_active = False
    await db.commit()
    return APIResponse(status="ok", message="تم إيقاف الموصّل", data=None, ref=ref)


@router.post("/subscriptions", status_code=201)
@limiter.limit("10/minute")
async def admin_create_subscription(
    body: SubscriptionCreate, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    plan = SubscriptionPlan(body.plan)
    price = PLAN_PRICES[plan]
    limit = PLAN_LIMITS[plan]
    sub = PharmacySubscription(
        pharmacy_name=body.pharmacy_name,
        pharmacy_id=uuid.UUID(body.pharmacy_id),
        plan=plan,
        price_tnd=price,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=True,
        delivery_count_this_month=0,
        delivery_limit=limit,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return APIResponse(status="ok", message="Subscription created", data={
        "id": str(sub.id),
        "pharmacy_name": sub.pharmacy_name,
        "plan": sub.plan.value,
        "price_tnd": float(sub.price_tnd),
        "expires_at": sub.expires_at.isoformat(),
    }, ref=ref)


@router.get("/subscriptions")
async def admin_list_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    subs = (await db.execute(
        select(PharmacySubscription).order_by(PharmacySubscription.started_at.desc())
    )).scalars().all()
    return APIResponse(status="ok", message="Subscriptions", data={
        "subscriptions": [
            {
                "id": str(s.id),
                "pharmacy_name": s.pharmacy_name,
                "pharmacy_id": str(s.pharmacy_id),
                "plan": s.plan.value,
                "price_tnd": float(s.price_tnd),
                "started_at": s.started_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "is_active": s.is_active,
                "delivery_count_this_month": s.delivery_count_this_month,
                "delivery_limit": s.delivery_limit,
            }
            for s in subs
        ],
    }, ref=ref)


@router.get("/payouts")
async def admin_list_payouts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN, Role.SUPER_ADMIN)),
    period: str = "all",
):
    ref = new_ref()
    now = datetime.utcnow()
    query = select(DriverPayout).order_by(DriverPayout.created_at.desc())
    if period == "week":
        week_start = now - timedelta(days=7)
        query = query.where(DriverPayout.created_at >= week_start)
    payouts = (await db.execute(query)).scalars().all()

    week_start = now - timedelta(days=7)
    week_total = await db.execute(
        select(func.coalesce(func.sum(DriverPayout.amount_tnd), 0))
        .where(DriverPayout.created_at >= week_start)
    )
    total_to_pay = float(week_total.scalar())

    return APIResponse(status="ok", message="Payouts", data={
        "payouts": [
            {
                "id": str(p.id),
                "driver_token_hash": p.driver_token_hash,
                "delivery_ticket_id": str(p.delivery_ticket_id),
                "amount_tnd": float(p.amount_tnd),
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in payouts
        ],
        "total_to_pay_this_week": total_to_pay,
    }, ref=ref)


@router.post("/payouts/{payout_id}/mark-paid")
@limiter.limit("10/minute")
async def admin_mark_payout_paid(
    payout_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    payout = await db.get(DriverPayout, payout_id)
    if not payout:
        raise NotFoundException("Payout not found", ref)
    payout.status = DriverPayoutStatus.PAID
    payout.paid_at = datetime.utcnow()
    await db.commit()
    return APIResponse(status="ok", message="Payout marqué payé", data={
        "id": str(payout.id),
        "status": payout.status.value,
    }, ref=ref)


@router.get("/revenue")
async def admin_revenue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active_subs = (await db.execute(
        select(PharmacySubscription).where(PharmacySubscription.is_active == True)
    )).scalars().all()
    mrr_tnd = sum(float(s.price_tnd) for s in active_subs)
    active_count = len(active_subs)

    top_plan_row = (await db.execute(
        select(PharmacySubscription.plan, func.count(PharmacySubscription.plan).label("cnt"))
        .where(PharmacySubscription.is_active == True)
        .group_by(PharmacySubscription.plan)
        .order_by(func.count(PharmacySubscription.plan).desc())
        .limit(1)
    )).first()
    top_plan = top_plan_row[0].value if top_plan_row else "N/A"

    commissions_result = await db.execute(
        select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
        .where(DeliveryCommission.created_at >= month_start)
    )
    commissions_tnd = float(commissions_result.scalar())

    deliveries_result = await db.execute(
        select(func.count(DeliveryTicket.id))
        .where(
            DeliveryTicket.is_fulfilled == True,
            DeliveryTicket.created_at >= month_start,
        )
    )
    deliveries_this_month = deliveries_result.scalar()

    pharmacy_earnings_result = await db.execute(
        select(func.coalesce(func.sum(PharmacySubscription.total_delivery_earnings), 0))
    )
    total_pharmacy_earnings = float(pharmacy_earnings_result.scalar())

    driver_payouts_result = await db.execute(
        select(func.coalesce(func.sum(DriverPayout.amount_tnd), 0))
        .where(DriverPayout.created_at >= month_start)
    )
    total_driver_payouts = float(driver_payouts_result.scalar())

    net_profit = mrr_tnd + commissions_tnd - total_driver_payouts

    revenue_history = []
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

        m_commissions = await db.execute(
            select(func.coalesce(func.sum(DeliveryCommission.commission_amount_tnd), 0))
            .where(DeliveryCommission.created_at >= month_start, DeliveryCommission.created_at < month_end)
        )
        m_payouts = await db.execute(
            select(func.coalesce(func.sum(DriverPayout.amount_tnd), 0))
            .where(DriverPayout.created_at >= month_start, DriverPayout.created_at < month_end)
        )
        m_mrr_result = await db.execute(
            select(func.coalesce(func.sum(PharmacySubscription.price_tnd), 0))
            .where(
                PharmacySubscription.is_active == True,
                PharmacySubscription.started_at < month_end,
            )
        )
        m_mrr = float(m_mrr_result.scalar())
        m_comm = float(m_commissions.scalar())
        m_pay = float(m_payouts.scalar())
        revenue_history.append({
            "month": f"{year}-{month:02d}",
            "mrr": m_mrr,
            "commissions": m_comm,
            "driver_payouts": m_pay,
            "net": m_mrr + m_comm - m_pay,
        })

    return APIResponse(status="ok", message="Revenue data", data={
        "mrr_tnd": mrr_tnd,
        "commissions_tnd": commissions_tnd,
        "active_subscriptions": active_count,
        "deliveries_this_month": deliveries_this_month,
        "top_plan": top_plan,
        "total_pharmacy_earnings": total_pharmacy_earnings,
        "total_driver_payouts": total_driver_payouts,
        "net_profit": net_profit,
        "revenue_history": revenue_history,
    }, ref=ref)


@router.get("/pharmacies")
async def admin_list_pharmacies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    subs = (await db.execute(
        select(PharmacySubscription).order_by(PharmacySubscription.started_at.desc())
    )).scalars().all()
    return APIResponse(status="ok", message="قائمة الصيدليات", data={
        "pharmacies": [
            {
                "id": str(s.id),
                "pharmacy_id": str(s.pharmacy_id),
                "pharmacy_name": s.pharmacy_name,
                "city": s.city,
                "plan": s.plan.value,
                "price_tnd": float(s.price_tnd),
                "is_active": s.is_active,
                "delivery_count_this_month": s.delivery_count_this_month,
                "delivery_limit": s.delivery_limit,
                "total_delivery_earnings": float(s.total_delivery_earnings),
                "started_at": s.started_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
            }
            for s in subs
        ],
    }, ref=ref)


@router.patch("/pharmacies/{pharmacy_id}/suspend")
async def admin_suspend_pharmacy(
    pharmacy_id: uuid.UUID, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.ADMIN)),
):
    ref = new_ref()
    sub = (await db.execute(
        select(PharmacySubscription).where(PharmacySubscription.pharmacy_id == pharmacy_id)
    )).scalar_one_or_none()
    if not sub:
        raise NotFoundException("Pharmacy not found", ref)
    sub.is_active = not sub.is_active
    await db.commit()
    status_text = "مفعل" if sub.is_active else "موقف"
    return APIResponse(status="ok", message=f"تم {status_text} الصيدلية", data={
        "pharmacy_id": str(sub.pharmacy_id),
        "is_active": sub.is_active,
    }, ref=ref)
