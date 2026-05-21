import uuid, hashlib, pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.models.prescription import Prescription
from app.models.delivery import Delivery
from app.models.user import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

DRV_HASH = hashlib.sha256(b"driver1").hexdigest()
DRV_HDRS = auth_headers("driver", DRV_HASH)
PH_HASH = hashlib.sha256(b"ph").hexdigest()
PH_HDRS = auth_headers("pharmacist", PH_HASH)


async def test_delivery_assign_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(User(id=DRV_HASH, role="driver", username="driver1", identity_id=DRV_HASH, hashed_password="test", is_active=True))
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=PH_HASH, status="verified", medications=[]))
    await db_session.commit()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "driver_id": DRV_HASH, "delivery_address": "123 Test St",
    }, headers=PH_HDRS)
    assert resp.status_code == 200
    assert "delivery_id" in resp.json()["data"]


async def test_delivery_fulfill_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    did = uuid.uuid4()
    db_session.add(User(id=DRV_HASH, role="driver", username="driver1", identity_id=DRV_HASH, hashed_password="test", is_active=True))
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=PH_HASH, status="verified", medications=[]))
    db_session.add(Delivery(
        id=did, prescription_id=pid, driver_id=DRV_HASH, pharmacy_id=PH_HASH,
        patient_id="patient-1", status="picked_up", otp_code="123456",
        otp_expires_at=datetime.utcnow() + timedelta(hours=2),
    ))
    await db_session.commit()
    resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "123456"}, headers=DRV_HDRS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "delivered"


async def test_fulfill_wrong_otp_returns_400(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    did = uuid.uuid4()
    db_session.add(User(id=DRV_HASH, role="driver", username="driver1", identity_id=DRV_HASH, hashed_password="test", is_active=True))
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=PH_HASH, status="verified", medications=[]))
    db_session.add(Delivery(
        id=did, prescription_id=pid, driver_id=DRV_HASH, pharmacy_id=PH_HASH,
        patient_id="patient-1", status="picked_up", otp_code="123456",
        otp_expires_at=datetime.utcnow() + timedelta(hours=2),
    ))
    await db_session.commit()
    resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "000000"}, headers=DRV_HDRS)
    assert resp.status_code == 400


async def test_assign_not_dispensed_returns_400(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=PH_HASH, status="pending", medications=[]))
    await db_session.commit()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "driver_id": DRV_HASH, "delivery_address": "123 Test St",
    }, headers=PH_HDRS)
    assert resp.status_code == 400  # Prescription is not ready (pending, not verified)
