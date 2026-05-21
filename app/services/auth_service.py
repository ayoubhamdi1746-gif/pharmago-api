from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
import structlog
logger = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

ADMIN_ROLES = {"admin", "super_admin"}
ACCESS_TOKEN_EXPIRE_HOURS_ADMIN = 24
ACCESS_TOKEN_EXPIRE_HOURS_DEFAULT = 8

BLACKLIST_PREFIX = "token:blacklist:"
REVOKED_SET = "tokens:revoked"

_blocklist_store: set[str] = set()
_redis_client = None


async def get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            from app.config import settings
            if settings.REDIS_URL:
                import redis as redis_module
                _redis_client = redis_module.from_url(settings.REDIS_URL)
        except Exception:
            pass
    return _redis_client


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        logger.error("verify_password_empty_hash")
        return False
    try:
        return pwd_context.verify(password, hashed)
    except Exception as e:
        logger.error("verify_password_exception", error=str(e), type=type(e).__name__)
        return False


def _token_expiry(role: str) -> timedelta:
    if role.lower() in ADMIN_ROLES:
        return timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS_ADMIN)
    return timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS_DEFAULT)


def create_access_token(subject: str, role: str, identity_id: str, jti: str | None = None) -> str:
    from app.config import settings
    if jti is None:
        import uuid
        jti = str(uuid.uuid4())

    expire = datetime.utcnow() + _token_expiry(role)
    payload = {
        "sub": subject,
        "role": role,
        "identity_id": identity_id,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": jti,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: str, identity_id: str, jti: str | None = None) -> str:
    from app.config import settings
    if jti is None:
        import uuid
        jti = str(uuid.uuid4())

    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "role": role,
        "identity_id": identity_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": jti,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token


async def revoke_token(token: str) -> None:
    """Revoke a token by decoding it and adding its JTI to the blocklist"""
    payload = decode_token(token)
    if payload:
        jti = payload.get("jti")
        token_type = payload.get("type", "access")
        if jti:
            _blocklist_store.add(f"{token_type}:{jti}")
            logger.info("token.revoked", jti=jti, type=token_type)


def is_token_revoked(jti: str, token_type: str) -> bool:
    key = f"{token_type}:{jti}"
    if key in _blocklist_store:
        return True
    return False


def decode_token(token: str) -> dict | None:
    from app.config import settings
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        jti = payload.get("jti")
        token_type = payload.get("type", "access")
        if jti and is_token_revoked(jti, token_type):
            return None
        return payload
    except JWTError:
        return None