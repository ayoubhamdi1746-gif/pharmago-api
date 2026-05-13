import pytest
from httpx import AsyncClient
from app.models.user import User
from app.services.auth_service import hash_password, create_access_token
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def test_login_success(client: AsyncClient, db_session):
    db_session.add(User(
        username="testuser", role="patient",
        identity_id="test-patient-ref",
        hashed_password=hash_password("secret123"),
        is_active=True,
    ))
    await db_session.commit()

    resp = await client.post("/auth/login", json={
        "username": "testuser", "password": "secret123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client: AsyncClient, db_session):
    db_session.add(User(
        username="testuser2", role="patient",
        identity_id="test-patient-ref",
        hashed_password=hash_password("secret123"),
        is_active=True,
    ))
    await db_session.commit()

    resp = await client.post("/auth/login", json={
        "username": "testuser2", "password": "wrongpass",
    })
    assert resp.status_code == 401


async def test_login_unknown_user_returns_401(client: AsyncClient):
    resp = await client.post("/auth/login", json={
        "username": "nobody", "password": "anything",
    })
    assert resp.status_code == 401


async def test_refresh_success(client: AsyncClient, db_session):
    user = User(
        username="refreshuser", role="pharmacist",
        identity_id="ph-identity",
        hashed_password=hash_password("pass"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_resp = await client.post("/auth/login", json={
        "username": "refreshuser", "password": "pass",
    })
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post("/auth/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_refresh_with_access_token_returns_401(client: AsyncClient, db_session):
    user = User(
        username="ref2", role="patient",
        identity_id="id",
        hashed_password=hash_password("pass"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    access = create_access_token(user.id, "patient", "id")
    resp = await client.post("/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


async def test_access_token_works_for_protected_endpoint(client: AsyncClient, db_session):
    user = User(
        username="protuser", role="patient",
        identity_id="prot-ref",
        hashed_password=hash_password("pass"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post("/auth/login", json={
        "username": "protuser", "password": "pass",
    })
    token = resp.json()["access_token"]

    resp2 = await client.get("/patient/my/deliveries", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
