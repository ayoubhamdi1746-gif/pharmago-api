import uuid, hashlib, pytest, hmac
from datetime import datetime
from httpx import AsyncClient
from app.config import settings
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import LethalRiskSubstance
from app.models.patient import MedicalRecord
from tests.conftest import generate_doctor_token, auth_headers

pytestmark = pytest.mark.asyncio

PATIENT_HDRS = auth_headers("patient", "test-patient-ref")
DOCTOR_HDRS = auth_headers("doctor", hashlib.sha256(b"doc1").hexdigest())


async def test_create_prescription_success(client: AsyncClient, db_session):
    db_session.add(MedicalRecord(reference_token="test-patient-ref", patient_weight_kg=70.0))
    await db_session.commit()
    resp = await client.post("/prescriptions", json={
        "patient_reference_token": "test-patient-ref",
        "items": [{"dpm_code": "SAFE01", "dose_mg": 10, "quantity": 1}],
    }, headers=PATIENT_HDRS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["status"] == "PENDING"


async def test_create_prescription_high_risk(client: AsyncClient, db_session):
    db_session.add(LethalRiskSubstance(
        dpm_code="LETHAL01", generic_name="Toxin",
        ld50_threshold_mg_per_kg=10.0, suicide_risk_flag=False,
    ))
    db_session.add(MedicalRecord(reference_token="test-patient-ref", patient_weight_kg=70.0))
    await db_session.commit()
    resp = await client.post("/prescriptions", json={
        "patient_reference_token": "test-patient-ref",
        "items": [{"dpm_code": "LETHAL01", "dose_mg": 500, "quantity": 1}],
    }, headers=PATIENT_HDRS)
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "HIGH_RISK_PENDING"


async def test_get_prescription_status(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="test-patient-ref", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    await db_session.commit()
    resp = await client.get(f"/prescriptions/{pid}/status", headers=PATIENT_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "PENDING"


async def test_doctor_confirm_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    doc_hash = hashlib.sha256(b"doc1").hexdigest()
    past = datetime.utcnow()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="HIGH_RISK_PENDING"))
    dcr = DoctorConfirmationRequest(
        prescription_id=pid, doctor_license_hash=doc_hash,
        requested_at=past, expires_at=past,
        status="AWAITING",
    )
    db_session.add(dcr)
    await db_session.commit()
    token = generate_doctor_token(pid, doc_hash, past.isoformat())
    resp = await client.post(f"/prescriptions/{pid}/doctor-confirm", json={
        "signed_token": token, "doctor_license_hash": doc_hash,
    }, headers=DOCTOR_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "PENDING"
