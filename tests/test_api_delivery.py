import uuid, hashlib, pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from cryptography.fernet import Fernet
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.delivery import VettedDriver, DeliveryTicket
from app.services.otp_service import generate_otp
from tests.conftest import TEST_FERNET_KEY, auth_headers

pytestmark = pytest.mark.asyncio

DRV_HASH = hashlib.sha256(b"driver1").hexdigest()
DRV_HDRS = auth_headers("driver", DRV_HASH)
PH_HASH = hashlib.sha256(b"ph").hexdigest()
PH_HDRS = auth_headers("pharmacist", PH_HASH)


async def test_delivery_assign_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(
        prescription_id=pid, status="DISPENSED", dispensed_at=datetime.utcnow(),
    ))
    db_session.add(VettedDriver(
        driver_token_hash=DRV_HASH, issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow() - timedelta(days=10),
        license_expires_at=datetime.utcnow() + timedelta(days=80),
        is_active=True,
    ))
    await db_session.commit()
    fernet = Fernet(TEST_FERNET_KEY)
    dropoff = fernet.encrypt(b"secret address").decode()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": dropoff,
    }, headers=PH_HDRS)
    assert resp.status_code == 201
    assert resp.json()["data"]["otp"] != ""


async def test_delivery_fulfill_success(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    plain_otp, otp_hash = generate_otp()
    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=DRV_HASH,
    ))
    await db_session.commit()
    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": plain_otp}, headers=DRV_HDRS)
    assert resp.status_code == 200


async def test_fulfill_wrong_otp_returns_403(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    _, otp_hash = generate_otp()
    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=DRV_HASH,
    ))
    await db_session.commit()
    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": "000000"}, headers=DRV_HDRS)
    assert resp.status_code == 403


async def test_assign_not_dispensed_returns_403(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    db_session.add(VettedDriver(
        driver_token_hash=DRV_HASH, issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow() - timedelta(days=10),
        license_expires_at=datetime.utcnow() + timedelta(days=80),
        is_active=True,
    ))
    await db_session.commit()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": "test",
    }, headers=PH_HDRS)
    assert resp.status_code == 403
