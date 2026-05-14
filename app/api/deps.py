from enum import Enum
from dataclasses import dataclass
from fastapi import Header, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.services.auth_service import decode_token

import structlog

logger = structlog.get_logger()


class Role(str, Enum):
    PATIENT = "patient"
    PHARMACIST = "pharmacist"
    DOCTOR = "doctor"
    DRIVER = "driver"
    ADMIN = "admin"


@dataclass
class UserContext:
    role: Role
    id: str


async def get_db() -> AsyncSession:
    if AsyncSessionLocal is None:
        raise HTTPException(503, "Database not available")
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    authorization: str = Header(..., alias="Authorization"),
) -> UserContext:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header format")
    token = authorization[7:]
    payload = decode_token(token)
    if payload is None:
        logger.warning("auth.invalid_token", token_prefix=token[:10])
        raise HTTPException(401, "Invalid or expired token")
    role_str = payload.get("role", "")
    identity_id = payload.get("identity_id", "")
    try:
        role = Role(role_str.lower())
    except ValueError:
        raise HTTPException(401, "Invalid role in token")
    return UserContext(role=role, id=identity_id)


def role_required(*roles: Role):
    async def check(user: UserContext = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Role not permitted")
        return user
    return check


def doctor_confirm_key(request: Request) -> str:
    token = request.headers.get("authorization", "")
    if token.startswith("Bearer "):
        payload = decode_token(token[7:])
        if payload:
            return payload.get("identity_id", "unknown")
    return request.client.host or "unknown"


def driver_fulfill_key(request: Request) -> str:
    token = request.headers.get("authorization", "")
    if token.startswith("Bearer "):
        payload = decode_token(token[7:])
        if payload:
            return payload.get("identity_id", "unknown")
    return request.client.host or "unknown"
