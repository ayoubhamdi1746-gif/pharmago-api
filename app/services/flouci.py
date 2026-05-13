from __future__ import annotations

import hmac
import hashlib
import httpx
from decimal import Decimal
from app.config import settings

FLOUCI_BASE = "https://developers.flouci.com"
FLOUCI_CREATE = f"{FLOUCI_BASE}/api/payments"


async def create_flouci_payment(
    amount_tnd: Decimal,
    phone: str,
    description: str,
    success_url: str,
    fail_url: str,
) -> dict:
    app_token = settings.FLOUCI_APP_TOKEN
    app_secret = settings.FLOUCI_APP_SECRET

    payload = {
        "app_token": app_token,
        "app_secret": app_secret,
        "amount": int(amount_tnd * 1000),
        "currency": "TND",
        "success_link": success_url,
        "fail_link": fail_url,
        "description": description,
        "phone": phone,
    }
    headers = {
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(FLOUCI_CREATE, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def verify_flouci_webhook(data: dict) -> bool:
    return data.get("status") == "success"


def verify_flouci_signature(payload_bytes: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = hmac.new(
        settings.FLOUCI_APP_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
