import uuid, hashlib, pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.config import Settings
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import LicensedPharmacist
from app.models.delivery import DeliveryTicket
from app.services.otp_service import generate_otp
from tests.conftest import generate_doctor_token, make_ref, auth_headers, make_jwt, TEST_JWT_SECRET

# ---------------------------------------------------------------------------
# Fix 1 – HMAC_SECRET validation (sync tests, no asyncio mark)
# ---------------------------------------------------------------------------

def test_hmac_secret_empty_raises():
    s = Settings(HMAC_SECRET="")
    with pytest.raises(RuntimeError, match="HMAC_SECRET.*at least 32"):
        s.validate_secure()


def test_hmac_secret_short_raises():
    s = Settings(HMAC_SECRET="short")
    with pytest.raises(RuntimeError, match="HMAC_SECRET.*at least 32"):
        s.validate_secure()


def test_hmac_secret_valid_passes():
    s = Settings(HMAC_SECRET="a" * 32)
    s.validate_secure()


# ---------------------------------------------------------------------------
# JWT_SECRET validation
# ---------------------------------------------------------------------------

def test_jwt_secret_empty_raises():
    s = Settings(JWT_SECRET="")
    with pytest.raises(RuntimeError, match="JWT_SECRET.*at least 32"):
        s.validate_secure()


def test_jwt_secret_short_raises():
    s = Settings(JWT_SECRET="short")
    with pytest.raises(RuntimeError, match="JWT_SECRET.*at least 32"):
        s.validate_secure()


def test_jwt_secret_valid_passes():
    s = Settings(JWT_SECRET="a" * 32)
    s.validate_secure()


# ---------------------------------------------------------------------------
# Fix 2 – signed_token_hash stores SHA-256, not the raw token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signed_token_hash_is_hash_not_raw(client: AsyncClient, db_session):
    pid = uuid.uuid4()
    doc_hash = hashlib.sha256(b"sec-doc").hexdigest()
    past = datetime.utcnow()

    db_session.add(LicensedPharmacist(
        pharmacist_license_hash=hashlib.sha256(b"sec-ph").hexdigest(),
        full_name_encrypted=b"enc", is_active=True,
    ))
    db_session.add(Prescription(id=pid, patient_reference_token="abc", items=[]))
    db_session.add(PrescriptionVerification(
        prescription_id=pid, status="HIGH_RISK_PENDING",
    ))
    dcr = DoctorConfirmationRequest(
        prescription_id=pid, doctor_license_hash=doc_hash,
        requested_at=past, expires_at=past + timedelta(hours=4),
        status="AWAITING",
    )
    db_session.add(dcr)
    await db_session.commit()

    token = generate_doctor_token(pid, doc_hash, past.isoformat())
    resp = await client.post(f"/prescriptions/{pid}/doctor-confirm", json={
        "signed_token": token, "doctor_license_hash": doc_hash,
    }, headers=auth_headers("doctor", doc_hash))
    assert resp.status_code == 200

    await db_session.refresh(dcr)
    expected_hash = hashlib.sha256(token.encode()).hexdigest()
    assert dcr.signed_token_hash == expected_hash, (
        "signed_token_hash should be SHA-256(token), not the raw token"
    )
    assert dcr.signed_token_hash != token, "Must NOT store the raw token"


# ---------------------------------------------------------------------------
# Fix 3 – OTP lockout after 5 failed attempts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_otp_lockout_after_5_failures(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    plain_otp, otp_hash = generate_otp()
    driver_hash = hashlib.sha256(b"lockout-drv").hexdigest()

    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=driver_hash,
    ))
    await db_session.commit()

    hdrs = auth_headers("driver", driver_hash)

    for i in range(5):
        resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": "000000"}, headers=hdrs)
        assert resp.status_code == 403

    ticket = await db_session.get(DeliveryTicket, tid)
    await db_session.refresh(ticket)
    assert ticket.locked_at is not None, "Ticket should be locked after 5 failures"
    assert ticket.failed_otp_attempts == 5

    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": plain_otp}, headers=hdrs)
    assert resp.status_code == 403
    data = resp.json()
    assert "locked" in data.get("message", "").lower()


# ---------------------------------------------------------------------------
# Fix 4 – OTP generated with secrets (6-digit range)
# ---------------------------------------------------------------------------

def test_otp_is_always_6_digits():
    for _ in range(100):
        otp, _ = generate_otp()
        assert len(otp) == 6
        assert 100000 <= int(otp) <= 999999


# ---------------------------------------------------------------------------
# Fix 5 – encrypted_dropoff is None after fulfill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_encrypted_dropoff_null_after_fulfill(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    plain_otp, otp_hash = generate_otp()
    driver_hash = hashlib.sha256(b"dropoff-null-drv").hexdigest()

    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc-here",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=driver_hash,
    ))
    await db_session.commit()

    hdrs = auth_headers("driver", driver_hash)
    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": plain_otp}, headers=hdrs)
    assert resp.status_code == 200

    ticket = await db_session.get(DeliveryTicket, tid)
    assert ticket.is_fulfilled is True
    assert ticket.encrypted_dropoff is None, "encrypted_dropoff should be None after fulfill"


# ---------------------------------------------------------------------------
# Fix 6 – wrong driver cannot fulfill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrong_driver_cannot_fulfill(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    plain_otp, otp_hash = generate_otp()
    assigned_driver_hash = hashlib.sha256(b"assigned-drv").hexdigest()
    wrong_driver_hash = hashlib.sha256(b"wrong-drv").hexdigest()

    db_session.add(DeliveryTicket(
        id=tid, prescription_id=uuid.uuid4(),
        pickup_coords="36.8,10.1", encrypted_dropoff=b"enc",
        otp_hash=otp_hash,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        driver_token_hash=assigned_driver_hash,
    ))
    await db_session.commit()

    hdrs = auth_headers("driver", wrong_driver_hash)
    resp = await client.post(f"/delivery/fulfill/{tid}", json={"otp": plain_otp}, headers=hdrs)
    assert resp.status_code == 403
    data = resp.json()
    assert "not assigned" in data.get("message", "").lower()


# ---------------------------------------------------------------------------
# New: expired token returns 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_jwt_returns_401(client: AsyncClient):
    from jose import jwt
    import time
    expired_payload = {
        "sub": "test-user",
        "role": "patient",
        "identity_id": "test",
        "type": "access",
        "exp": int(time.time()) - 3600,
        "iat": int(time.time()) - 4000,
    }
    expired_token = jwt.encode(expired_payload, TEST_JWT_SECRET, algorithm="HS256")
    resp = await client.get("/patient/my/deliveries", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# New: forged token (wrong secret) returns 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forged_jwt_returns_401(client: AsyncClient):
    from jose import jwt
    forged = jwt.encode(
        {"sub": "fake", "role": "patient", "identity_id": "fake", "type": "access", "exp": 9999999999, "iat": 0},
        "different-secret-that-is-not-the-test-secret!",
        algorithm="HS256",
    )
    resp = await client.get("/patient/my/deliveries", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
