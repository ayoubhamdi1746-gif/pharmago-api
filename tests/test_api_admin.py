import uuid, hashlib, pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from app.models.delivery import VettedDriver
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

ADMIN_HDRS = auth_headers("admin", "admin-key")
PHARM_HDRS = auth_headers("pharmacist", "ph-key")


async def test_admin_create_driver(client: AsyncClient, db_session):
    resp = await client.post("/admin/drivers", json={
        "driver_id": "test-driver-1",
        "pharmacy_id": "00000000-0000-0000-0000-000000000001",
    }, headers=ADMIN_HDRS)
    assert resp.status_code == 201
    assert "driver_token_hash" in resp.json()["data"]


async def test_admin_suspend_driver(client: AsyncClient, db_session):
    token_hash = hashlib.sha256(b"suspend-test").hexdigest()
    db_session.add(VettedDriver(
        driver_token_hash=token_hash, issuing_pharmacy_id=uuid.uuid4(),
        license_issued_at=datetime.utcnow(),
        license_expires_at=datetime.utcnow() + timedelta(days=90),
        is_active=True,
    ))
    await db_session.commit()
    resp = await client.patch(f"/admin/drivers/{token_hash}/suspend", json={}, headers=ADMIN_HDRS)
    assert resp.status_code == 200


async def test_non_admin_cannot_create_driver(client: AsyncClient, db_session):
    resp = await client.post("/admin/drivers", json={
        "driver_id": "test",
        "pharmacy_id": "00000000-0000-0000-0000-000000000001",
    }, headers=PHARM_HDRS)
    assert resp.status_code == 403
