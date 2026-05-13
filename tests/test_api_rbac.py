import uuid, hashlib, pytest, hmac
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.services.otp_service import generate_otp
from app.config import settings
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.delivery import VettedDriver, DeliveryTicket
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
        db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
        db_session.add(PrescriptionVerification(prescription_id=pid, status="HIGH_RISK_PENDING"))
        db_session.add(DoctorConfirmationRequest(
            prescription_id=pid, doctor_license_hash=doc_hash,
            requested_at=past, expires_at=past, status="AWAITING",
        ))
    await db_session.commit()

    token_a = generate_doctor_token(pid_a, doc_hash, past.isoformat())
    resp = await client.post(f"/prescriptions/{pid_b}/doctor-confirm", json={
        "signed_token": token_a, "doctor_license_hash": doc_hash,
    }, headers=auth_headers("doctor", doc_hash))
    assert resp.status_code == 403


async def test_fulfill_wrong_otp_returns_403(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    _, otp_hash = generate_otp()
    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=hashlib.sha256(b"rbac-drv").hexdigest(),
    ))
    await db_session.commit()
    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": "000000"}, headers=DRIVER_HDRS)
    assert resp.status_code == 403


async def test_assign_not_dispensed_returns_403(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    db_session.add(VettedDriver(
        driver_token_hash=hashlib.sha256(b"rbac-drv").hexdigest(), issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow() - timedelta(days=10),
        license_expires_at=datetime.utcnow() + timedelta(days=80),
        is_active=True,
    ))
    await db_session.commit()
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "pickup_coords": "36.8,10.1", "encrypted_dropoff": "x",
    }, headers=auth_headers("pharmacist", hashlib.sha256(b"rbac-ph").hexdigest()))
    assert resp.status_code == 403
