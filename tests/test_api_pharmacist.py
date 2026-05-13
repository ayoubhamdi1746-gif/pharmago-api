import uuid, hashlib, pytest
from datetime import datetime
from httpx import AsyncClient
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.pharmacy import LicensedPharmacist
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

PH_HASH = hashlib.sha256(b"ph1").hexdigest()
PH_HDRS = auth_headers("pharmacist", PH_HASH)


async def test_pharmacist_verify_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(LicensedPharmacist(
        pharmacist_license_hash=PH_HASH, full_name_encrypted=b"name", is_active=True,
    ))
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    await db_session.commit()
    resp = await client.post(f"/pharmacist/verify/{pid}", json={
        "pharmacist_license_hash": PH_HASH,
    }, headers=PH_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "VERIFIED"


async def test_pharmacist_dispense_success(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(
        prescription_id=pid, status="VERIFIED", verified_at=datetime.utcnow(),
    ))
    await db_session.commit()
    resp = await client.post(f"/pharmacist/dispense/{pid}", json={}, headers=PH_HDRS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "DISPENSED"


async def test_dispense_not_verified_returns_403(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    await db_session.commit()
    resp = await client.post(f"/pharmacist/dispense/{pid}", json={}, headers=PH_HDRS)
    assert resp.status_code == 403


async def test_verify_high_risk_without_token_returns_403(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    db_session.add(LicensedPharmacist(
        pharmacist_license_hash=PH_HASH, full_name_encrypted=b"name", is_active=True,
    ))
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="HIGH_RISK_PENDING"))
    await db_session.commit()
    resp = await client.post(f"/pharmacist/verify/{pid}", json={
        "pharmacist_license_hash": PH_HASH,
    }, headers=PH_HDRS)
    assert resp.status_code == 403
