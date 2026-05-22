import uuid, hashlib, pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.config import Settings
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.pharmacy import LicensedPharmacist
from app.models.delivery import DeliveryTicket, Delivery
from app.models.user import User
from app.services.otp_service import generate_otp
from tests.conftest import generate_doctor_token, make_ref, auth_headers, make_jwt, TEST_JWT_SECRET

# ---------------------------------------------------------------------------
# Fix 1 – HMAC_SECRET / JWT_SECRET / FERNET_KEY auto-generation
# ---------------------------------------------------------------------------

def test_empty_secrets_are_auto_generated():
    s = Settings(HMAC_SECRET="", JWT_SECRET="", FERNET_KEY="")
    assert len(s.HMAC_SECRET) >= 32
    assert len(s.JWT_SECRET) >= 32
    assert len(s.FERNET_KEY) >= 32


def test_short_secrets_are_auto_generated():
    s = Settings(HMAC_SECRET="short", JWT_SECRET="tiny", FERNET_KEY="wee")
    assert len(s.HMAC_SECRET) >= 32
    assert len(s.JWT_SECRET) >= 32
    assert len(s.FERNET_KEY) >= 32


def test_valid_secrets_passed_through():
    s = Settings(HMAC_SECRET="a" * 32, JWT_SECRET="b" * 32, FERNET_KEY="c" * 32)
    assert s.HMAC_SECRET == "a" * 32
    assert s.JWT_SECRET == "b" * 32
    assert s.FERNET_KEY == "c" * 32


# ---------------------------------------------------------------------------
# Fix 2 – signed_token_hash stores SHA-256, not the raw token (via new API)
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
    db_session.add(Prescription(id=pid, patient_id="abc", pharmacy_id="abc", medications=[]))
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

    resp = await client.post(f"/doctor/confirm/{pid}", json={}, headers=auth_headers("doctor", doc_hash))
    assert resp.status_code == 200

    await db_session.refresh(dcr)
    assert dcr.signed_token_hash is not None, "signed_token_hash should be set"
    assert len(dcr.signed_token_hash) == 64, "signed_token_hash should be SHA-256 hex digest (64 chars)"


# ---------------------------------------------------------------------------
# Fix 3 – OTP is always 6 digits
# ---------------------------------------------------------------------------

def test_otp_is_always_6_digits():
    for _ in range(100):
        otp, _ = generate_otp()
        assert len(otp) == 6
        assert 100000 <= int(otp) <= 999999


# ---------------------------------------------------------------------------
# Fix 4 – OTP lockout via delivery API (current Delivery model)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_otp_lockout_after_5_failures(client: AsyncClient, db_session):
    # Current Delivery model doesn't have OTP lockout.
    # Test that wrong OTP returns 400 (invalid OTP)
    pid = uuid.uuid4()
    drv_hash = hashlib.sha256(b"lockout-drv").hexdigest()
    db_session.add(User(id=drv_hash, role="driver", username="lockout-drv", identity_id=drv_hash, hashed_password="test", is_active=True))
    db_session.add(Prescription(id=pid, patient_id="patient-1", pharmacy_id=drv_hash, status="verified", medications=[]))
    await db_session.commit()

    # Assign
    resp = await client.post(f"/delivery/assign/{pid}", json={
        "driver_id": drv_hash, "delivery_address": "123 Test St",
    }, headers=auth_headers("pharmacist", drv_hash))
    assert resp.status_code == 200
    did = resp.json()["data"]["delivery_id"]

    # Pickup
    resp = await client.patch(f"/delivery/{did}/pickup", json={}, headers=auth_headers("driver", drv_hash))
    assert resp.status_code == 200

    # Wrong OTP 5 times — first 4 return 400, 5th returns 429 (locked)
    for i in range(4):
        resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "000000"}, headers=auth_headers("driver", drv_hash))
        assert resp.status_code == 400, f"attempt {i+1} expected 400"
    resp = await client.patch(f"/delivery/{did}/deliver", json={"otp_code": "000000"}, headers=auth_headers("driver", drv_hash))
    assert resp.status_code == 429  # locked


# ---------------------------------------------------------------------------
# Fix 5 – expired JWT returns 401
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
# Fix 6 – forged JWT returns 401
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
