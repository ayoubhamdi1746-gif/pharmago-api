import uuid, hashlib, pytest
from datetime import datetime, timedelta
from decimal import Decimal
from httpx import AsyncClient
from cryptography.fernet import Fernet
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.delivery import VettedDriver, DeliveryTicket
from app.models.billing import PharmacySubscription, DeliveryCommission, DriverPayout, DriverPayoutStatus, SubscriptionPlan, CommissionStatus
from app.services.otp_service import generate_otp
from tests.conftest import TEST_FERNET_KEY, auth_headers

pytestmark = pytest.mark.asyncio

DRV_HASH = hashlib.sha256(b"billing-driver").hexdigest()
DRV_HDRS = auth_headers("driver", DRV_HASH)
PH_HASH = hashlib.sha256(b"billing-ph").hexdigest()
PH_HDRS = auth_headers("pharmacist", PH_HASH)
ADMIN_HDRS = auth_headers("admin", "admin-key")

PHARMACY_ID = uuid.uuid4()


async def _seed_dispensed(db_session, extra_deliveries: int = 0) -> uuid.UUID:
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="billing-test", items=[{"dpm_code": "SAFE01", "dose_mg": 10, "quantity": 1}]))
    db_session.add(PrescriptionVerification(
        prescription_id=pid, status="DISPENSED", dispensed_at=datetime.utcnow(),
    ))
    db_session.add(VettedDriver(
        driver_token_hash=DRV_HASH, issuing_pharmacy_id=PHARMACY_ID,
        license_issued_at=datetime.utcnow() - timedelta(days=10),
        license_expires_at=datetime.utcnow() + timedelta(days=80),
        is_active=True,
    ))
    await db_session.commit()
    return pid


async def test_commission_auto_created_on_fulfillment(client: AsyncClient, db_session):
    pid = await _seed_dispensed(db_session)
    fernet = Fernet(TEST_FERNET_KEY)
    dropoff = fernet.encrypt(b"test address").decode()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": dropoff,
    }, headers=PH_HDRS)
    assert resp.status_code == 201
    ticket_id = resp.json()["data"]["ticket_id"]
    otp = resp.json()["data"]["otp"]

    resp = await client.post(f"/delivery/fulfill/{ticket_id}", json={"otp": otp}, headers=DRV_HDRS)
    assert resp.status_code == 200

    commissions = (await db_session.execute(
        __import__("sqlalchemy").select(DeliveryCommission)
    )).scalars().all()
    assert len(commissions) == 1
    assert commissions[0].delivery_ticket_id == uuid.UUID(ticket_id)
    assert commissions[0].commission_amount_tnd == Decimal("3.00")
    assert commissions[0].status == CommissionStatus.PENDING


async def test_driver_payout_and_pharmacy_earnings_on_fulfillment(client: AsyncClient, db_session):
    sub = PharmacySubscription(
        pharmacy_name="Payout Pharmacy",
        pharmacy_id=PHARMACY_ID,
        plan=SubscriptionPlan.PRO,
        price_tnd=Decimal("450.00"),
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=True,
        delivery_count_this_month=0,
        delivery_limit=None,
    )
    db_session.add(sub)
    await db_session.commit()

    pid = await _seed_dispensed(db_session)
    fernet = Fernet(TEST_FERNET_KEY)
    dropoff = fernet.encrypt(b"test address").decode()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": dropoff,
    }, headers=PH_HDRS)
    assert resp.status_code == 201
    ticket_id = resp.json()["data"]["ticket_id"]
    otp = resp.json()["data"]["otp"]

    resp = await client.post(f"/delivery/fulfill/{ticket_id}", json={"otp": otp}, headers=DRV_HDRS)
    assert resp.status_code == 200

    payouts = (await db_session.execute(
        __import__("sqlalchemy").select(DriverPayout)
    )).scalars().all()
    assert len(payouts) == 1
    assert payouts[0].delivery_ticket_id == uuid.UUID(ticket_id)
    assert payouts[0].amount_tnd == Decimal("3.00")
    assert payouts[0].status == DriverPayoutStatus.PENDING

    updated_sub = await db_session.get(PharmacySubscription, sub.id)
    assert updated_sub.total_delivery_earnings == Decimal("1.00")


async def test_starter_plan_blocks_at_50_deliveries(client: AsyncClient, db_session):
    sub = PharmacySubscription(
        pharmacy_name="Test Pharmacy",
        pharmacy_id=PHARMACY_ID,
        plan=SubscriptionPlan.STARTER,
        price_tnd=Decimal("200.00"),
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=True,
        delivery_count_this_month=50,
        delivery_limit=50,
    )
    db_session.add(sub)
    await db_session.commit()

    pid = await _seed_dispensed(db_session)
    fernet = Fernet(TEST_FERNET_KEY)
    dropoff = fernet.encrypt(b"test address").decode()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": dropoff,
    }, headers=PH_HDRS)
    assert resp.status_code == 403
    assert "Limite du plan" in resp.json()["message"]


async def test_admin_revenue_returns_correct_totals(client: AsyncClient, db_session):
    sub = PharmacySubscription(
        pharmacy_name="Revenue Pharmacy",
        pharmacy_id=uuid.uuid4(),
        plan=SubscriptionPlan.PRO,
        price_tnd=Decimal("450.00"),
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=True,
        delivery_count_this_month=0,
        delivery_limit=None,
    )
    db_session.add(sub)
    await db_session.commit()

    resp = await client.get("/admin/revenue", headers=ADMIN_HDRS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mrr_tnd"] == 450.0
    assert data["active_subscriptions"] == 1
    assert data["top_plan"] == "PRO"
    assert isinstance(data["commissions_tnd"], float)
    assert isinstance(data["deliveries_this_month"], int)
    assert "total_pharmacy_earnings" in data
    assert "total_driver_payouts" in data
    assert "net_profit" in data


async def test_admin_creates_subscription(client: AsyncClient, db_session):
    resp = await client.post("/admin/subscriptions", json={
        "pharmacy_name": "New Pharmacy",
        "pharmacy_id": str(uuid.uuid4()),
        "plan": "STARTER",
    }, headers=ADMIN_HDRS)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["pharmacy_name"] == "New Pharmacy"
    assert data["plan"] == "STARTER"
    assert data["price_tnd"] == 200.0

    subs = (await db_session.execute(
        __import__("sqlalchemy").select(PharmacySubscription)
    )).scalars().all()
    assert len(subs) == 1
    assert subs[0].delivery_limit == 50
