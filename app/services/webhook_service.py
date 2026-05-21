import json, hmac, hashlib, structlog
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.webhook_subscription import WebhookSubscription, WebhookDelivery
from app.config import settings

logger = structlog.get_logger()


async def dispatch_webhook(
    db: AsyncSession,
    event: str,
    payload: dict[str, Any],
    pharmacy_id: str | None = None,
) -> list[dict]:
    query = select(WebhookSubscription).where(
        WebhookSubscription.is_active == True,
    )
    if pharmacy_id:
        query = query.where(WebhookSubscription.pharmacy_id == pharmacy_id)
    result = await db.execute(query)
    subs = result.scalars().all()

    import httpx
    results = []
    for sub in subs:
        if event not in sub.events:
            continue
        body = json.dumps({"event": event, "payload": payload}, default=str).encode()
        sig = hmac.new(sub.secret.encode(), body, hashlib.sha256).hexdigest()
        delivery_id = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    sub.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": sig,
                        "X-Webhook-Event": event,
                    },
                )
            success = resp.is_success
            delivery = WebhookDelivery(
                id=delivery_id,
                subscription_id=sub.id,
                event=event,
                payload=payload,
                response_status=str(resp.status_code),
                response_body=resp.text[:2000],
                success=success,
                created_at=datetime.now(timezone.utc),
            )
            if success:
                sub.last_triggered_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error("webhook_delivery_failed", sub_id=sub.id, event=event, error=str(e))
            delivery = WebhookDelivery(
                id=delivery_id,
                subscription_id=sub.id,
                event=event,
                payload=payload,
                response_status="error",
                response_body=str(e)[:2000],
                success=False,
                next_retry_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
        db.add(delivery)
        results.append({"subscription_id": sub.id, "delivery_id": delivery_id, "success": delivery.success})
    if results:
        await db.flush()
    return results


import uuid
