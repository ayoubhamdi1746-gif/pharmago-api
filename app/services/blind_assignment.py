import uuid, hmac, random, asyncio, structlog
from datetime import datetime, timedelta
from decimal import Decimal
from cryptography.fernet import Fernet
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.delivery import DeliveryTicket, VettedDriver
from app.models.prescription import PrescriptionVerification
from app.models.billing import PharmacySubscription, DeliveryCommission, DriverPayout, DriverPayoutStatus, SubscriptionPlan, CommissionStatus
from app.exceptions.handlers import ForbiddenException, NotFoundException, ConflictException
from app.config import settings
from app.logging.cfg import new_ref
from app.services.otp_service import generate_otp, verify_otp

logger = structlog.get_logger()

MAX_FAILED_ATTEMPTS = 5
COMMISSION_AMOUNT_TND = Decimal("3.00")
DRIVER_PAYOUT_AMOUNT_TND = Decimal("3.00")
PHARMACY_EARNING_PER_DELIVERY = Decimal("1.00")

PLAN_DELIVERY_LIMITS = {
    SubscriptionPlan.STARTER: 50,
    SubscriptionPlan.PRO: None,
    SubscriptionPlan.ENTERPRISE: None,
}


class BlindAssignmentEngine:
    def __init__(self, db: AsyncSession, fernet_key: bytes):
        self.db = db
        self.fernet = Fernet(fernet_key)

    async def assign(self, prescription_id: uuid.UUID, pickup_coords: str,
                     encrypted_dropoff: str, ref: str | None = None) -> DeliveryTicket:
        if ref is None:
            ref = new_ref()
        pv = (await self.db.execute(
            select(PrescriptionVerification).where(
                PrescriptionVerification.prescription_id == prescription_id))
        ).scalar_one_or_none()
        if not pv or pv.status != "DISPENSED":
            raise ForbiddenException("Delivery requires DISPENSED status", ref)
        delay = random.uniform(settings.MIN_ASSIGN_DELAY_SEC, settings.MAX_ASSIGN_DELAY_SEC)
        await asyncio.sleep(delay)
        now = datetime.utcnow()
        drivers = (await self.db.execute(
            select(VettedDriver).where(
                VettedDriver.is_active == True,
                VettedDriver.license_expires_at > now))
        ).scalars().all()
        if not drivers:
            raise ForbiddenException("No eligible driver available", ref)
        driver = random.choice(drivers)

        sub = (await self.db.execute(
            select(PharmacySubscription).where(
                PharmacySubscription.pharmacy_id == driver.issuing_pharmacy_id,
                PharmacySubscription.is_active == True,
            )
        )).scalar_one_or_none()
        if sub and sub.plan == SubscriptionPlan.STARTER:
            limit = PLAN_DELIVERY_LIMITS[SubscriptionPlan.STARTER]
            if sub.delivery_count_this_month >= limit:
                raise ForbiddenException(
                    "Limite du plan atteinte — passez au plan Pro", ref,
                )

        plain_otp, otp_hash = generate_otp()
        drop_bytes = self.fernet.encrypt(encrypted_dropoff.encode())
        ticket = DeliveryTicket(
            prescription_id=prescription_id, pickup_coords=pickup_coords,
            encrypted_dropoff=drop_bytes, otp_hash=otp_hash,
            expires_at=now + timedelta(minutes=settings.DELIVERY_TICKET_TTL_MINUTES),
            driver_token_hash=driver.driver_token_hash,
        )
        self.db.add(ticket)
        await self.db.commit()
        logger.info("Delivery ticket created", ref=ref, presc=str(prescription_id))
        ticket._plain_otp = plain_otp
        return ticket

    async def fulfill(self, ticket_id: uuid.UUID, otp: str, driver_token: str, ref: str | None = None) -> None:
        if ref is None:
            ref = new_ref()
        ticket = await self.db.get(DeliveryTicket, ticket_id)
        if not ticket:
            raise NotFoundException("Delivery ticket not found", ref)
        if ticket.is_fulfilled:
            raise ConflictException("Delivery ticket already fulfilled", ref)
        if ticket.expires_at < datetime.utcnow():
            raise ForbiddenException("Delivery ticket expired", ref)
        if ticket.locked_at is not None:
            raise ForbiddenException("Delivery ticket is locked due to too many failed attempts", ref)
        if ticket.driver_token_hash != driver_token:
            logger.warning("Driver token mismatch", ref=ref, ticket=str(ticket_id), expected=ticket.driver_token_hash, got=driver_token)
            raise ForbiddenException("This ticket is not assigned to you", ref)
        if not verify_otp(otp, ticket.otp_hash):
            ticket.failed_otp_attempts = (ticket.failed_otp_attempts or 0) + 1
            if ticket.failed_otp_attempts >= MAX_FAILED_ATTEMPTS:
                ticket.locked_at = datetime.utcnow()
                logger.warning("Delivery ticket locked due to OTP failures", ref=ref, ticket=str(ticket_id), attempts=ticket.failed_otp_attempts)
            await self.db.commit()
            raise ForbiddenException("Invalid OTP", ref)
        ticket.is_fulfilled = True
        ticket.encrypted_dropoff = None

        commission = DeliveryCommission(
            delivery_ticket_id=ticket_id,
            commission_amount_tnd=COMMISSION_AMOUNT_TND,
        )
        self.db.add(commission)

        payout = DriverPayout(
            driver_token_hash=ticket.driver_token_hash,
            delivery_ticket_id=ticket_id,
            amount_tnd=DRIVER_PAYOUT_AMOUNT_TND,
        )
        self.db.add(payout)

        driver = (await self.db.execute(
            select(VettedDriver).where(
                VettedDriver.driver_token_hash == ticket.driver_token_hash
            )
        )).scalar_one_or_none()
        if driver:
            sub = (await self.db.execute(
                select(PharmacySubscription).where(
                    PharmacySubscription.pharmacy_id == driver.issuing_pharmacy_id,
                    PharmacySubscription.is_active == True,
                )
            )).scalar_one_or_none()
            if sub:
                sub.delivery_count_this_month = (sub.delivery_count_this_month or 0) + 1
                sub.total_delivery_earnings = (sub.total_delivery_earnings or Decimal("0.00")) + PHARMACY_EARNING_PER_DELIVERY

        await self.db.commit()
        logger.info("Delivery fulfilled", ref=ref, ticket=str(ticket_id))
