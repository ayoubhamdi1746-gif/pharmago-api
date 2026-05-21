import uuid, hashlib, hmac
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from httpx import AsyncClient, ASGITransport

from app.database import Base
from app.config import settings
from app.models.patient import PatientIdentity, MedicalRecord
from app.models.pharmacy import LicensedPharmacist, LethalRiskSubstance, ControlledSubstance
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.delivery import VettedDriver, DeliveryTicket
from app.models.abuse import AbuseFlag
from app.models.user import User
from app.models.billing import PharmacySubscription, DeliveryCommission, SubscriptionPlan
from app.models.payment import PaymentTransaction
from app.models.password_reset import PasswordResetOTP
from app.services.auth_service import hash_password


TEST_FERNET_KEY = Fernet.generate_key()
TEST_HMAC_SECRET = "test-hmac-secret-for-pharmago-xx!!"
TEST_JWT_SECRET = "test-jwt-secret-thats-at-least-32-chars!!"


@pytest.fixture(autouse=True)
def patch_settings():
    settings.MIN_ASSIGN_DELAY_SEC = 0.0
    settings.MAX_ASSIGN_DELAY_SEC = 0.0
    settings.FERNET_KEY = TEST_FERNET_KEY.decode()
    settings.HMAC_SECRET = TEST_HMAC_SECRET
    settings.JWT_SECRET = TEST_JWT_SECRET
    settings.FULFILL_RATE_LIMIT = "1000/minute"
    settings.KONNECT_API_KEY = "test_konnect_key"
    settings.KONNECT_WALLET_ID = "test_konnect_wallet"
    settings.FLOUCI_APP_TOKEN = "test_flouci_token"
    settings.FLOUCI_APP_SECRET = "test_flouci_secret"
    from app.limiter import limiter
    limiter.reset()


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    yield session
    await trans.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(db_session):
    from app.api.deps import get_db
    from app.main import create_app
    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_ref():
    return str(uuid.uuid4())


def generate_doctor_token(prescription_id, doctor_hash, timestamp):
    payload = f"{prescription_id}:{doctor_hash}:{timestamp}"
    return hmac.new(
        TEST_HMAC_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def make_jwt(role: str, identity_id: str, secret: str = TEST_JWT_SECRET) -> str:
    from jose import jwt
    payload = {
        "sub": str(uuid.uuid4()),
        "role": role,
        "identity_id": identity_id,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_headers(role: str, identity_id: str) -> dict:
    return {"Authorization": f"Bearer {make_jwt(role, identity_id)}"}
