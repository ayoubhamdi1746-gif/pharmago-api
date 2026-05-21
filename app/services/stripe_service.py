import structlog
from typing import Any
from decimal import Decimal

logger = structlog.get_logger()


async def create_stripe_payment_intent(
    amount_tnd: Decimal,
    description: str,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        from app.config import settings
        # TODO: Integrate Stripe SDK
        logger.info("stripe.payment_intent_created", amount=float(amount_tnd), description=description)
        return {
            "id": f"pi_mock_{amount_tnd}",
            "client_secret": f"cs_mock_{amount_tnd}",
            "amount": int(amount_tnd * 100),
            "currency": "usd",
            "status": "requires_payment_method",
        }
    except Exception as e:
        logger.error("stripe.error", error=str(e))
        raise


async def create_stripe_account(pharmacy_name: str, email: str) -> dict[str, Any]:
    try:
        # TODO: Create Stripe Connect account
        logger.info("stripe.connect_account_created", pharmacy_name=pharmacy_name)
        return {"id": f"acct_mock_{pharmacy_name}", "charges_enabled": True}
    except Exception as e:
        logger.error("stripe.connect_error", error=str(e))
        raise


async def create_transfer(amount_tnd: Decimal, destination: str) -> dict[str, Any]:
    try:
        logger.info("stripe.transfer_created", amount=float(amount_tnd), destination=destination)
        return {"id": f"tr_mock_{amount_tnd}", "amount": int(amount_tnd * 100), "status": "pending"}
    except Exception as e:
        logger.error("stripe.transfer_error", error=str(e))
        raise
