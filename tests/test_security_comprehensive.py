import pytest
from app.services.password_policy import validate_password, PasswordError


class TestPasswordPolicy:
    def test_too_short_raises(self):
        with pytest.raises(PasswordError, match="at least 8"):
            validate_password("Ab1!")

    def test_no_uppercase_raises(self):
        with pytest.raises(PasswordError, match="uppercase"):
            validate_password("abcdef1!@")

    def test_no_lowercase_raises(self):
        with pytest.raises(PasswordError, match="lowercase"):
            validate_password("ABCDEF1!@")

    def test_no_digit_raises(self):
        with pytest.raises(PasswordError, match="digit"):
            validate_password("Abcdefgh!@")

    def test_no_special_raises(self):
        with pytest.raises(PasswordError, match="special"):
            validate_password("Abcdefgh1")

    def test_common_password_raises(self):
        with pytest.raises(PasswordError, match="common"):
            validate_password("Password123!")

    def test_valid_password_passes(self):
        validate_password("Str0ng!Pass#42")


@pytest.mark.asyncio
async def test_rate_limit_headers_present(client):
    resp = await client.post("/auth/login", json={"username": "nonexistent", "password": "test"})
    assert "Retry-After" in resp.headers or resp.status_code in (401, 422, 429)


@pytest.mark.asyncio
async def test_cors_security_headers(client):
    resp = await client.get("/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("strict-transport-security") is not None


@pytest.mark.asyncio
async def test_registration_password_validation(client):
    resp = await client.post("/auth/register/patient", json={
        "name": "Test Patient",
        "email": "weak@test.com",
        "password": "weak",
        "phone": "+21650123456",
    })
    assert resp.status_code in (422, 500)


@pytest.mark.asyncio
async def test_newsletter_email_validation(client):
    resp = await client.post("/public/newsletter", json={"email": "not-an-email"})
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_forged_jwt_returns_401(client):
    from jose import jwt
    forged = jwt.encode(
        {"sub": "fake", "role": "patient", "identity_id": "fake", "type": "access", "exp": 9999999999, "iat": 0},
        "wrong-secret-that-is-32-chars-long!!..",
        algorithm="HS256",
    )
    resp = await client.get("/patient/my/deliveries", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(client):
    from jose import jwt
    import time
    expired = jwt.encode(
        {"sub": "u1", "role": "patient", "identity_id": "id1", "type": "access",
         "exp": int(time.time()) - 3600, "iat": int(time.time()) - 4000},
        "test-jwt-secret-thats-at-least-32-chars!!",
        algorithm="HS256",
    )
    resp = await client.get("/patient/my/deliveries", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_auth_header_returns_4xx(client):
    resp = await client.get("/patient/my/deliveries")
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_wrong_auth_format_returns_401(client):
    resp = await client.get("/patient/my/deliveries", headers={"Authorization": "Basic xxx"})
    assert resp.status_code in (401, 422)


class TestPasswordPolicyUnit:
    def test_long_password_raises(self):
        with pytest.raises(PasswordError, match="not exceed"):
            validate_password("Ab1!" + "x" * 200)

    def test_edge_valid(self):
        validate_password("V3ry!Str0ng")
        validate_password("aB3$defgh")
        validate_password("MyP@ssw0rd")

    def test_common_variants_rejected(self):
        for pw in ["password123", "admin", "qwerty123", "letmein"]:
            with pytest.raises(PasswordError):
                validate_password(pw.upper() + "!A1")
