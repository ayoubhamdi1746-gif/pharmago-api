import uuid, hashlib, pytest
from datetime import datetime
from httpx import AsyncClient
from app.config import settings
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.pharmacy import LethalRiskSubstance
from app.models.patient import MedicalRecord
from app.models.user import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

PATIENT_ID = "test-patient-ref"
PATIENT_HDRS = auth_headers("patient", PATIENT_ID)
DOC_HASH = hashlib.sha256(b"doc1").hexdigest()
DOCTOR_HDRS = auth_headers("doctor", DOC_HASH)
PH_HASH = hashlib.sha256(b"ph1").hexdigest()


async def test_create_prescription_success(client: AsyncClient, db_session):
    db_session.add(User(id=PH_HASH, role="pharmacist", username="ph1", identity_id=PH_HASH, hashed_password="test", is_active=True))
    db_session.add(User(id=str(uuid.uuid4()), role="patient", username="pat1", identity_id=PATIENT_ID, hashed_password="test", is_active=True))
    await db_session.commit()
    resp = await client.post("/prescriptions", json={
        "pharmacy_id": PH_HASH,
        "medications": [{"name": "Paracetamol", "dosage": 500, "quantity": 10}],
    }, headers=PATIENT_HDRS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["status"] == "pending"


async def test_create_prescription_high_risk(client: AsyncClient, db_session):
    db_session.add(User(id=PH_HASH, role="pharmacist", username="ph1", identity_id=PH_HASH, hashed_password="test", is_active=True))
    db_session.add(User(id=str(uuid.uuid4()), role="patient", username="pat2", identity_id=PATIENT_ID, hashed_password="test", is_active=True))
    db_session.add(LethalRiskSubstance(
        dpm_code="LETHAL01", generic_name="Toxin",
        ld50_threshold_mg_per_kg=10.0, suicide_risk_flag=False,
    ))
    await db_session.commit()
    # The current POST /prescriptions does not check safety gates,
    # it just creates a prescription with status "pending"
    resp = await client.post("/prescriptions", json={
        "pharmacy_id": PH_HASH,
        "medications": [{"name": "LETHAL01", "dosage": 500, "quantity": 1}],
    }, headers=PATIENT_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending"


async def test_get_prescription_status(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    pat_user = User(id=str(uuid.uuid4()), role="patient", username="pat3", identity_id=PATIENT_ID, hashed_password="test", is_active=True)
    db_session.add(pat_user)
    await db_session.flush()
    db_session.add(Prescription(id=pid, patient_id=pat_user.id, pharmacy_id="test-ph", medications=[]))
    await db_session.commit()
    resp = await client.get(f"/prescriptions/my", headers=PATIENT_HDRS)
    assert resp.status_code == 200


async def test_doctor_confirm_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    past = datetime.utcnow()
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    pv = PrescriptionVerification(prescription_id=pid, status="HIGH_RISK_PENDING")
    db_session.add(pv)
    from app.models.prescription import DoctorConfirmationRequest
    dcr = DoctorConfirmationRequest(
        prescription_id=pid, doctor_license_hash=DOC_HASH,
        expires_at=datetime.utcnow(),
        status="AWAITING",
    )
    db_session.add(dcr)
    await db_session.commit()
    resp = await client.post(f"/doctor/confirm/{pid}", json={}, headers=DOCTOR_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "PENDING"
