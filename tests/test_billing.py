import uuid, hashlib, pytest
from datetime import datetime, timedelta
from decimal import Decimal
from httpx import AsyncClient
from app.models.prescription import Prescription
from app.models.delivery import Delivery
from app.models.billing import PharmacySubscription, SubscriptionPlan
from app.models.user import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

DRV_HASH = hashlib.sha256(b"billing-driver").hexdigest()
DRV_HDRS = auth_headers("driver", DRV_HASH)
PH_HASH = hashlib.sha256(b"billing-ph").hexdigest()
PH_HDRS = auth_headers("pharmacist", PH_HASH)
ADMIN_HDRS = auth_headers("admin", "admin-key")

PHARMACY_ID = uuid.uuid4()


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


async def test_delivery_flow_with_driver(client: AsyncClient, db_session):
    """Test a complete delivery flow creates proper records"""
    did = uuid.uuid4()
    pid = uuid.uuid4()
    db_session.add(User(id=DRV_HASH, role="driver", username="billing-driver", identity_id=DRV_HASH, hashed_password="test", is_active=True))
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=PH_HASH, status="verified", medications=[]))
    db_session.add(Delivery(
        id=did, prescription_id=pid, driver_id=DRV_HASH, pharmacy_id=PH_HASH,
        patient_id="patient-1", status="assigned", otp_code="123456",
        otp_expires_at=datetime.utcnow() + timedelta(hours=2),
    ))
    await db_session.commit()

    # Pickup
    resp = await client.patch(f"/delivery/{did}/pickup", json={}, headers=DRV_HDRS)
    assert resp.status_code == 200

    # Deliver
    resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "123456"}, headers=DRV_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "delivered"
