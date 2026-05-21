import uuid, structlog
from datetime import datetime, timezone
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog
from app.api.deps import UserContext

logger = structlog.get_logger()


async def log_audit(
    db: AsyncSession,
    action: str,
    actor: UserContext | None = None,
    request: Request | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    ref: str | None = None,
) -> str:
    entry_id = str(uuid.uuid4())
    entry = AuditLog(
        id=entry_id,
        actor_id=actor.id if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500] if request else None,
        ref=ref,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
    logger.info("audit", action=action, actor=actor.id if actor else None, resource=resource_type, ref=ref)
    return entry_id
