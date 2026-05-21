import uuid
import hashlib
import pytest
from datetime import datetime, timedelta
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import LicensedPharmacist
from app.services.verification_gate import verify_prescription
from app.services.verification_helpers import check_modification_allowed
from app.exceptions.handlers import ForbiddenException
from tests.conftest import make_ref, generate_doctor_token

pytestmark = pytest.mark.asyncio


async def test_driver_cannot_read_prescription(db_session):
    """a) Driver token cannot be used as pharmacist license."""
    ref = make_ref()
    pid = uuid.uuid4()
    driver_token = hashlib.sha256(b"driver_token").hexdigest()

    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(prescription_id=pid, status="PENDING"))
    await db_session.commit()

    with pytest.raises(ForbiddenException) as exc:
        await verify_prescription(db_session, pid, driver_token, ref=ref)
    assert "not licensed" in str(exc.value.message)


async def test_modify_after_verified_returns_403(db_session):
    """d) Modifying prescription after VERIFIED is forbidden."""
    ref = make_ref()
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(
        id=uuid.uuid4(), prescription_id=pid,
        status="VERIFIED", verified_at=datetime.utcnow(),
    ))
    await db_session.commit()

    with pytest.raises(ForbiddenException) as exc:
        await check_modification_allowed(db_session, pid, ref)
    assert "Cannot modify after VERIFIED" in str(exc.value.message)


async def test_pharmacist_approves_high_risk_without_token_returns_403(db_session):
    """e) Pharmacist cannot verify HIGH_RISK_PENDING without token."""
    ref = make_ref()
    ph_hash = hashlib.sha256(b"ph1").hexdigest()
    pid = uuid.uuid4()

    db_session.add(LicensedPharmacist(
        pharmacist_license_hash=ph_hash,
        full_name_encrypted=b"encrypted_name", is_active=True,
    ))
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(
        id=uuid.uuid4(), prescription_id=pid, status="HIGH_RISK_PENDING",
    ))
    await db_session.commit()

    with pytest.raises(ForbiddenException) as exc:
        await verify_prescription(db_session, pid, ph_hash, ref=ref)
    assert "requires doctor_signed_token" in str(exc.value.message)


async def test_expired_doctor_token_returns_to_high_risk_pending(db_session):
    """h) Expired doctor_signed_token cannot verify HIGH_RISK_PENDING."""
    ref = make_ref()
    ph_hash = hashlib.sha256(b"ph2").hexdigest()
    pid = uuid.uuid4()
    doc_hash = hashlib.sha256(b"doc1").hexdigest()
    past = datetime.utcnow() - timedelta(hours=10)

    db_session.add(LicensedPharmacist(
        pharmacist_license_hash=ph_hash, full_name_encrypted=b"enc", is_active=True,
    ))
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(
        id=uuid.uuid4(), prescription_id=pid, status="HIGH_RISK_PENDING",
    ))
    dcr = DoctorConfirmationRequest(
        prescription_id=pid, doctor_license_hash=doc_hash,
        requested_at=past, expires_at=past + timedelta(hours=4), status="AWAITING",
    )
    db_session.add(dcr)
    await db_session.commit()

    expired_token = generate_doctor_token(pid, doc_hash, past.isoformat())
    with pytest.raises(ForbiddenException) as exc:
        await verify_prescription(
            db_session, pid, ph_hash, doctor_signed_token=expired_token, ref=ref,
        )
    assert "expired" in str(exc.value.message).lower()
    await db_session.refresh(dcr)
    assert dcr.status == "EXPIRED"
