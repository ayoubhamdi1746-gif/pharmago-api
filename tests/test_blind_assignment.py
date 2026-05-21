import uuid
import hashlib
import pytest
from datetime import datetime, timedelta
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.delivery import VettedDriver, DeliveryTicket
from app.services.blind_assignment import BlindAssignmentEngine
from app.exceptions.handlers import ForbiddenException, ConflictException
from tests.conftest import make_ref, TEST_FERNET_KEY

pytestmark = pytest.mark.asyncio


async def test_completed_ticket_reuse_returns_409(db_session):
    """b) Fulfilled ticket cannot be used again."""
    ref = make_ref()
    tid = uuid.uuid4()
    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=hashlib.sha256(b"123456").hexdigest(),
        expires_at=datetime.utcnow() + timedelta(hours=1),
        is_fulfilled=True, driver_token_hash="abc",
    ))
    await db_session.commit()

    engine = BlindAssignmentEngine(db_session, TEST_FERNET_KEY)
    with pytest.raises(ConflictException) as exc:
        await engine.fulfill(tid, "123456", driver_token="abc", ref=ref)
    assert "already fulfilled" in str(exc.value.message)


async def test_delivery_without_dispensed_returns_403(db_session):
    """c) Delivery ticket cannot be created without DISPENSED status."""
    ref = make_ref()
    pid = uuid.uuid4()
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(
        id=uuid.uuid4(), prescription_id=pid,
        status="VERIFIED", verified_at=datetime.utcnow(),
    ))
    db_session.add(VettedDriver(
        driver_token_hash=hashlib.sha256(b"d1").hexdigest(),
        issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow() - timedelta(days=10),
        license_expires_at=datetime.utcnow() + timedelta(days=80),
        is_active=True,
    ))
    await db_session.commit()

    engine = BlindAssignmentEngine(db_session, TEST_FERNET_KEY)
    with pytest.raises(ForbiddenException) as exc:
        await engine.assign(pid, "36.8,10.1", "secret", ref=ref)
    assert "requires DISPENSED" in str(exc.value.message)


async def test_expired_driver_assignment_returns_403(db_session):
    """f) Assigning an expired driver is forbidden."""
    ref = make_ref()
    pid = uuid.uuid4()

    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
    db_session.add(PrescriptionVerification(
        id=uuid.uuid4(), prescription_id=pid,
        status="DISPENSED", dispensed_at=datetime.utcnow(),
    ))
    db_session.add(VettedDriver(
        driver_token_hash=hashlib.sha256(b"expired").hexdigest(),
        issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow() - timedelta(days=100),
        license_expires_at=datetime.utcnow() - timedelta(days=10),
        is_active=True,
    ))
    await db_session.commit()

    engine = BlindAssignmentEngine(db_session, TEST_FERNET_KEY)
    with pytest.raises(ForbiddenException) as exc:
        await engine.assign(pid, "36.8,10.1", "secret", ref=ref)
    assert "No eligible driver available" in str(exc.value.message)
