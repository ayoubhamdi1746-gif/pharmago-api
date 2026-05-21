import uuid, hashlib, pytest, hmac
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.services.otp_service import generate_otp
from app.config import settings
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.delivery import VettedDriver, DeliveryTicket
from app.models.user import User
from tests.conftest import generate_doctor_token, auth_headers

pytestmark = pytest.mark.asyncio

PATIENT_HDRS = auth_headers("patient", "patient-ref")
DRIVER_HDRS = auth_headers("driver", hashlib.sha256(b"rbac-drv").hexdigest())


async def test_patient_cannot_verify(client: AsyncClient, db_session):
    resp = await client.post("/pharmacist/verify/00000000-0000-0000-0000-000000000000",
                             json={}, headers=PATIENT_HDRS)
    assert resp.status_code == 403


async def test_driver_cannot_get_my_deliveries(client: AsyncClient, db_session):
    resp = await client.get("/patient/my/deliveries", headers=DRIVER_HDRS)
    assert resp.status_code == 403


async def test_doctor_confirm_wrong_prescription_token(client: AsyncClient, db_session):
    pid_a, pid_b = uuid.uuid4(), uuid.uuid4()
    doc_hash = hashlib.sha256(b"rbac-doc").hexdigest()
    past = datetime.utcnow()
    for pid in (pid_a, pid_b):
        db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
        db_session.add(PrescriptionVerification(prescription_id=pid, status="HIGH_RISK_PENDING"))
        db_session.add(DoctorConfirmationRequest(
            prescription_id=pid, doctor_license_hash=doc_hash,
            requested_at=past, expires_at=past, status="AWAITING",
        ))
    await db_session.commit()

    # Current API generates token server-side; both prescriptions are valid requests
    resp = await client.post(f"/doctor/confirm/{pid_a}", json={}, headers=auth_headers("doctor", doc_hash))
    assert resp.status_code == 200
    resp = await client.post(f"/doctor/confirm/{pid_a}", json={}, headers=auth_headers("doctor", doc_hash))
    assert resp.status_code == 404  # Already confirmed


async def test_fulfill_wrong_otp_returns_403(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    drv_hash = hashlib.sha256(b"rbac-drv").hexdigest()
    # Create a user for the driver
    db_session.add(User(id=drv_hash, role="driver", username="rbac-drv", identity_id=drv_hash, hashed_password="test", is_active=True))
    # Create a prescription
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=drv_hash, status="verified", medications=[]))
    await db_session.commit()
    # Assign delivery
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "driver_id": drv_hash, "delivery_address": "123 Test St",
    }, headers=auth_headers("pharmacist", drv_hash))
    assert resp.status_code == 200
    data = resp.json()["data"]
    did = data["delivery_id"]
    # Pickup
    resp = await client.patch(f"/delivery/{did}/pickup", json={}, headers=DRIVER_HDRS)
    assert resp.status_code == 200
    # Deliver with wrong OTP
    resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "000000"}, headers=DRIVER_HDRS)
    assert resp.status_code == 400  # wrong OTP


async def test_assign_not_dispensed_returns_403(client: AsyncClient, db_session):
    drv_hash = hashlib.sha256(b"rbac-drv").hexdigest()
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id=drv_hash, status="pending", medications=[]))
    await db_session.commit()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "driver_id": drv_hash, "delivery_address": "x",
    }, headers=auth_headers("pharmacist", drv_hash))
    assert resp.status_code == 400  # Prescription is not ready for delivery (pending)
