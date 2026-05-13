from __future__ import annotations

import hmac
import hashlib
import httpx
from decimal import Decimal
from app.config import settings

KONNECT_BASE = "https://api.konnect.network"
KONNECT_CREATE = f"{KONNECT_BASE}/api/v1/payments"


async def create_konnect_payment(
    amount_tnd: Decimal,
    phone: str,
    description: str,
    success_url: str,
    fail_url: str,
    notification_url: str,
) -> dict:
    api_key = settings.KONNECT_API_KEY
    wallet_id = settings.KONNECT_WALLET_ID

    payload = {
        "amount": int(amount_tnd * 1000),
        "currency": "TND",
        "description": description,
        "notification_url": notification_url,
        "success_url": success_url,
        "fail_url": fail_url,
        "order_id": description,
        "customer": {"phone": phone},
    }
    headers = {
        "x-api-key": api_key,
        "wallet-id": wallet_id,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(KONNECT_CREATE, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def verify_konnect_webhook(pay_id: str, status: str) -> bool:
    return status == "success"


def verify_konnect_signature(payload_bytes: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = hmac.new(
        settings.KONNECT_API_KEY.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
