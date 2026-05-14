from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

ADMIN_ROLES = {"admin", "super_admin"}
ACCESS_TOKEN_EXPIRE_HOURS_ADMIN = 24
ACCESS_TOKEN_EXPIRE_HOURS_DEFAULT = 8


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def _token_expiry(role: str) -> timedelta:
    if role.lower() in ADMIN_ROLES:
        return timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS_ADMIN)
    return timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS_DEFAULT)


def create_access_token(subject: str, role: str, identity_id: str) -> str:
    expire = datetime.utcnow() + _token_expiry(role)
    payload = {
        "sub": subject,
        "role": role,
        "identity_id": identity_id,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: str, identity_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "role": role,
        "identity_id": identity_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
