import uuid, hashlib, hmac, json, pytest
from datetime import datetime, timedelta
from decimal import Decimal
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from app.models.billing import PharmacySubscription, SubscriptionPlan
from app.models.payment import PaymentTransaction, PaymentProvider, PaymentStatus
from app.config import settings
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

ADMIN_HDRS = auth_headers("admin", "admin-key")


async def test_billing_subscribe_returns_payment_url(client: AsyncClient, db_session):
    with patch("app.api.billing.create_konnect_payment", new_callable=AsyncMock) as mock_k:
        mock_k.return_value = {"payment_url": "https://konnect.test/pay/123", "pay_id": "pay_123"}
        resp = await client.post("/billing/subscribe", json={
            "pharmacy_name": "Konnect Pharmacy",
            "plan": "STARTER",
            "phone": "+21650123456",
            "payment_provider": "KONNECT",
        })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "https://konnect.test/pay/123" in data["payment_url"]
    assert data["provider"] == "KONNECT"

    txns = (await db_session.execute(
        __import__("sqlalchemy").select(PaymentTransaction)
    )).scalars().all()
    assert len(txns) == 1
    assert txns[0].provider == PaymentProvider.KONNECT
    assert txns[0].status == PaymentStatus.PENDING
    assert txns[0].amount_tnd == Decimal("200.00")

    subs = (await db_session.execute(
        __import__("sqlalchemy").select(PharmacySubscription)
    )).scalars().all()
    assert len(subs) == 1
    assert subs[0].is_active == False


async def test_billing_subscribe_flouci(client: AsyncClient, db_session):
    with patch("app.api.billing.create_flouci_payment", new_callable=AsyncMock) as mock_f:
        mock_f.return_value = {"result": {"payment_url": "https://flouci.test/pay/456", "id": "flouci_456"}}
        resp = await client.post("/billing/subscribe", json={
            "pharmacy_name": "Flouci Pharmacy",
            "plan": "PRO",
            "phone": "+21650789123",
            "payment_provider": "FLOUCI",
        })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "https://flouci.test/pay/456" in data["payment_url"]
    assert data["provider"] == "FLOUCI"


async def test_konnect_webhook_activates_subscription(client: AsyncClient, db_session):
    sub = PharmacySubscription(
        pharmacy_name="Webhook Pharmacy",
        pharmacy_id=uuid.uuid4(),
        plan=SubscriptionPlan.STARTER,
        price_tnd=Decimal("200.00"),
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=False,
        delivery_count_this_month=0,
        delivery_limit=50,
    )
    db_session.add(sub)
    await db_session.commit()

    txn = PaymentTransaction(
        subscription_id=sub.id,
        provider=PaymentProvider.KONNECT,
        provider_payment_id="pay_webhook_789",
        amount_tnd=Decimal("200.00"),
        phone="+21650123456",
        payment_url="https://konnect.test/pay/789",
        status=PaymentStatus.PENDING,
    )
    db_session.add(txn)
    await db_session.commit()

    payload = {"pay_id": "pay_webhook_789", "status": "success"}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(settings.KONNECT_API_KEY.encode(), body_bytes, hashlib.sha256).hexdigest()
    resp = await client.post("/billing/webhook/konnect", content=body_bytes, headers={"x-konnect-signature": sig, "content-type": "application/json"})
    assert resp.status_code == 200

    updated_sub = (await db_session.execute(
        __import__("sqlalchemy").select(PharmacySubscription).where(PharmacySubscription.id == sub.id)
    )).scalar_one()
    assert updated_sub.is_active == True

    updated_txn = (await db_session.execute(
        __import__("sqlalchemy").select(PaymentTransaction).where(PaymentTransaction.id == txn.id)
    )).scalar_one()
    assert updated_txn.status == PaymentStatus.COMPLETED


async def test_flouci_webhook_activates_subscription(client: AsyncClient, db_session):
    sub = PharmacySubscription(
        pharmacy_name="Flouci Webhook Pharm",
        pharmacy_id=uuid.uuid4(),
        plan=SubscriptionPlan.PRO,
        price_tnd=Decimal("450.00"),
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=False,
        delivery_count_this_month=0,
        delivery_limit=None,
    )
    db_session.add(sub)
    await db_session.commit()

    txn = PaymentTransaction(
        subscription_id=sub.id,
        provider=PaymentProvider.FLOUCI,
        provider_payment_id="flouci_webhook_101",
        amount_tnd=Decimal("450.00"),
        phone="+21650789123",
        payment_url="https://flouci.test/pay/101",
        status=PaymentStatus.PENDING,
    )
    db_session.add(txn)
    await db_session.commit()

    payload = {"payment_id": "flouci_webhook_101", "status": "success"}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(settings.FLOUCI_APP_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    resp = await client.post("/billing/webhook/flouci", content=body_bytes, headers={"x-flouci-signature": sig, "content-type": "application/json"})
    assert resp.status_code == 200

    updated_sub = (await db_session.execute(
        __import__("sqlalchemy").select(PharmacySubscription).where(PharmacySubscription.id == sub.id)
    )).scalar_one()
    assert updated_sub.is_active == True
