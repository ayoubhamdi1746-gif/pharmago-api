import uuid, hashlib, structlog
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.limiter import limiter
from app.schemas.common import APIResponse, BillingSubscribe, RegisterPharmacyRequest
from app.models.user import User
from app.models.billing import PharmacySubscription, SubscriptionPlan, PLAN_PRICES, PLAN_LIMITS
from app.models.payment import PaymentTransaction, PaymentProvider, PaymentStatus
from app.services.konnect import create_konnect_payment, verify_konnect_webhook, verify_konnect_signature
from app.services.flouci import create_flouci_payment, verify_flouci_webhook, verify_flouci_signature
from app.services.auth_service import hash_password
from app.logging.cfg import new_ref
from app.config import settings

router = APIRouter()
logger = structlog.get_logger()

BASE_CALLBACK = "https://api.pharmago.tn"


@router.post("/register-pharmacy")
@limiter.limit("3/minute")
async def billing_register_pharmacy(
    body: RegisterPharmacyRequest, request: Request,
    db: AsyncSession = Depends(get_db),
):
    ref = new_ref()
    try:
        plan_enum = SubscriptionPlan(body.plan.upper())
    except ValueError:
        return APIResponse(status="error", message="Invalid plan", ref=ref)

    price = PLAN_PRICES[plan_enum]
    limit = PLAN_LIMITS[plan_enum]
    pharmacy_id = uuid.uuid4()
    username = f"pharm_{body.pharmacy_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
    pwd = body.password or uuid.uuid4().hex[:12]
    identity_id = hashlib.sha256(f"{username}:{pharmacy_id}".encode()).hexdigest()

    user = User(
        username=username,
        role="pharmacist",
        identity_id=identity_id,
        hashed_password=hash_password(pwd),
        is_active=False,
        pharmacy_id=str(pharmacy_id),
        city=body.city,
        email=body.email or None,
    )
    db.add(user)

    sub = PharmacySubscription(
        pharmacy_name=body.pharmacy_name,
        pharmacy_id=pharmacy_id,
        city=body.city,
        responsible_name=body.responsible_name,
        plan=plan_enum,
        price_tnd=price,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=False,
        delivery_count_this_month=0,
        delivery_limit=limit,
        total_delivery_earnings=Decimal("0.00"),
    )
    db.add(sub)
    await db.flush()

    success_url = f"{BASE_CALLBACK}/billing/success?sub_id={sub.id}"
    fail_url = f"{BASE_CALLBACK}/billing/fail?sub_id={sub.id}"
    notification_url = f"{BASE_CALLBACK}/billing/webhook/{body.payment_provider.lower()}"

    provider = PaymentProvider(body.payment_provider)
    payment_url = None
    provider_payment_id = None

    if provider == PaymentProvider.KONNECT:
        try:
            konnect_resp = await create_konnect_payment(
                amount_tnd=price,
                phone=body.phone,
                description=f"PharmaGo {plan_enum.value} - {body.pharmacy_name}",
                success_url=success_url,
                fail_url=fail_url,
                notification_url=notification_url,
            )
            payment_url = konnect_resp.get("payment_url")
            provider_payment_id = str(konnect_resp.get("pay_id", ""))
        except Exception as e:
            logger.error("konnect_payment_failed", error=str(e), ref=ref)
            await db.rollback()
            return APIResponse(status="error", message="Konnect payment failed", ref=ref)

    elif provider == PaymentProvider.FLOUCI:
        try:
            flouci_resp = await create_flouci_payment(
                amount_tnd=price,
                phone=body.phone,
                description=f"PharmaGo {plan_enum.value} - {body.pharmacy_name}",
                success_url=success_url,
                fail_url=fail_url,
            )
            flouci_data = flouci_resp.get("result", {})
            payment_url = flouci_data.get("payment_url") or flouci_data.get("link")
            provider_payment_id = str(flouci_data.get("id", ""))
        except Exception as e:
            logger.error("flouci_payment_failed", error=str(e), ref=ref)
            await db.rollback()
            return APIResponse(status="error", message="Flouci payment failed", ref=ref)

    txn = PaymentTransaction(
        subscription_id=sub.id,
        provider=provider,
        provider_payment_id=provider_payment_id,
        amount_tnd=price,
        phone=body.phone,
        payment_url=payment_url,
        status=PaymentStatus.PENDING,
    )
    db.add(txn)
    await db.commit()

    return APIResponse(status="ok", message="Inscription créée, en attente de paiement", data={
        "payment_url": payment_url,
        "transaction_id": str(txn.id),
        "username": username,
        "pharmacy_id": str(pharmacy_id),
    }, ref=ref)


@router.post("/subscribe")
@limiter.limit("5/minute")
async def billing_subscribe(
    body: BillingSubscribe, request: Request,
    db: AsyncSession = Depends(get_db),
):
    ref = new_ref()
    plan = SubscriptionPlan(body.plan)
    price = PLAN_PRICES[plan]
    limit = PLAN_LIMITS[plan]

    sub = PharmacySubscription(
        pharmacy_name=body.pharmacy_name,
        pharmacy_id=uuid.uuid4(),
        plan=plan,
        price_tnd=price,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=False,
        delivery_count_this_month=0,
        delivery_limit=limit,
    )
    db.add(sub)
    await db.flush()

    success_url = f"{BASE_CALLBACK}/billing/success?sub_id={sub.id}"
    fail_url = f"{BASE_CALLBACK}/billing/fail?sub_id={sub.id}"
    notification_url = f"{BASE_CALLBACK}/billing/webhook/{body.payment_provider.lower()}"

    provider = PaymentProvider(body.payment_provider)
    payment_url = None
    provider_payment_id = None

    if provider == PaymentProvider.KONNECT:
        try:
            konnect_resp = await create_konnect_payment(
                amount_tnd=price,
                phone=body.phone,
                description=f"PharmaGo {plan.value} - {body.pharmacy_name}",
                success_url=success_url,
                fail_url=fail_url,
                notification_url=notification_url,
            )
            payment_url = konnect_resp.get("payment_url")
            provider_payment_id = str(konnect_resp.get("pay_id", ""))
        except Exception as e:
            logger.error("konnect_payment_failed", error=str(e), ref=ref)
            await db.rollback()
            return APIResponse(status="error", message="Konnect payment failed", ref=ref)

    elif provider == PaymentProvider.FLOUCI:
        try:
            flouci_resp = await create_flouci_payment(
                amount_tnd=price,
                phone=body.phone,
                description=f"PharmaGo {plan.value} - {body.pharmacy_name}",
                success_url=success_url,
                fail_url=fail_url,
            )
            flouci_data = flouci_resp.get("result", {})
            payment_url = flouci_data.get("payment_url") or flouci_data.get("link")
            provider_payment_id = str(flouci_data.get("id", ""))
        except Exception as e:
            logger.error("flouci_payment_failed", error=str(e), ref=ref)
            await db.rollback()
            return APIResponse(status="error", message="Flouci payment failed", ref=ref)

    txn = PaymentTransaction(
        subscription_id=sub.id,
        provider=provider,
        provider_payment_id=provider_payment_id,
        amount_tnd=price,
        phone=body.phone,
        payment_url=payment_url,
        status=PaymentStatus.PENDING,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    return APIResponse(status="ok", message="Payment link generated", data={
        "payment_url": payment_url,
        "transaction_id": str(txn.id),
        "provider": provider.value,
    }, ref=ref)


@router.post("/webhook/konnect")
@limiter.limit("10/minute")
async def konnect_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ref = new_ref()
    import json
    body_bytes = await request.body()
    sig = request.headers.get("x-konnect-signature")
    if not verify_konnect_signature(body_bytes, sig):
        logger.warning("konnect_webhook_hmac_failed", ref=ref)
        return APIResponse(status="error", message="Invalid webhook signature", ref=ref)

    body = json.loads(body_bytes)
    pay_id = body.get("pay_id", "")
    status = body.get("status", "")

    if not verify_konnect_webhook(pay_id, status):
        return APIResponse(status="error", message="Invalid webhook", ref=ref)

    txn = (await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.provider == PaymentProvider.KONNECT,
            PaymentTransaction.provider_payment_id == pay_id,
        )
    )).scalar_one_or_none()
    if not txn:
        return APIResponse(status="error", message="Transaction not found", ref=ref)

    txn.status = PaymentStatus.COMPLETED
    txn.completed_at = datetime.utcnow()
    if txn.subscription_id:
        sub = (await db.execute(
            select(PharmacySubscription).where(PharmacySubscription.id == txn.subscription_id)
        )).scalar_one_or_none()
        if sub:
            sub.is_active = True
            user = (await db.execute(
                select(User).where(User.pharmacy_id == str(sub.pharmacy_id))
            )).scalar_one_or_none()
            if user:
                user.is_active = True
    await db.commit()
    return APIResponse(status="ok", message="Payment confirmed", ref=ref)


@router.post("/webhook/flouci")
@limiter.limit("10/minute")
async def flouci_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ref = new_ref()
    import json
    body_bytes = await request.body()
    sig = request.headers.get("x-flouci-signature")
    if not verify_flouci_signature(body_bytes, sig):
        logger.warning("flouci_webhook_hmac_failed", ref=ref)
        return APIResponse(status="error", message="Invalid webhook signature", ref=ref)

    body = json.loads(body_bytes)
    if not verify_flouci_webhook(body):
        return APIResponse(status="error", message="Invalid webhook", ref=ref)

    payment_id = body.get("payment_id", "")
    txn = (await db.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.provider == PaymentProvider.FLOUCI,
            PaymentTransaction.provider_payment_id == payment_id,
        )
    )).scalar_one_or_none()
    if not txn:
        return APIResponse(status="error", message="Transaction not found", ref=ref)

    txn.status = PaymentStatus.COMPLETED
    txn.completed_at = datetime.utcnow()
    if txn.subscription_id:
        sub = (await db.execute(
            select(PharmacySubscription).where(PharmacySubscription.id == txn.subscription_id)
        )).scalar_one_or_none()
        if sub:
            sub.is_active = True
            user = (await db.execute(
                select(User).where(User.pharmacy_id == str(sub.pharmacy_id))
            )).scalar_one_or_none()
            if user:
                user.is_active = True
    await db.commit()
    return APIResponse(status="ok", message="Payment confirmed", ref=ref)
