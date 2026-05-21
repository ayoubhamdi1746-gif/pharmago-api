import structlog
from typing import Any

logger = structlog.get_logger()


async def send_sms(phone: str, message: str) -> bool:
    try:
        from app.config import settings
        if settings.DEV_MODE:
            logger.info("sms.dev", phone=phone, message=message)
            return True
        # TODO: Integrate Twilio
        logger.info("sms.sent", phone=phone, message_preview=message[:50])
        return True
    except Exception as e:
        logger.error("sms.failed", error=str(e), phone=phone)
        return False


async def send_email(to: str, subject: str, body: str) -> bool:
    try:
        from app.config import settings
        if settings.DEV_MODE:
            logger.info("email.dev", to=to, subject=subject)
            return True
        if settings.SENDGRID_API_KEY:
            import ssl, http.client, json
            conn = http.client.HTTPSConnection("api.sendgrid.com", context=ssl.create_default_context())
            payload = json.dumps({
                "personalizations": [{"to": [{"email": to}], "subject": subject}],
                "from": {"email": "noreply@pharmago.tn", "name": "PharmaGo"},
                "content": [{"type": "text/html", "value": body}],
            })
            conn.request("POST", "/v3/mail/send", payload, {
                "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            })
            resp = conn.getresponse()
            conn.close()
            if resp.status == 202:
                logger.info("email.sent", to=to, subject=subject)
                return True
            logger.warning("email.sendgrid_error", status=resp.status, to=to)
            return False
        if settings.SMTP_HOST:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body, "html")
            msg["Subject"] = subject
            msg["From"] = f"PharmaGo <{settings.SMTP_USER or 'noreply@pharmago.tn'}>"
            msg["To"] = to
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info("email.sent", to=to, subject=subject)
            return True
        logger.info("email.sent.stub", to=to, subject=subject)
        return True
    except Exception as e:
        logger.error("email.failed", error=str(e), to=to)
        return False


async def send_otp_sms(phone: str, otp: str) -> bool:
    return await send_sms(phone, f"PharmaGo: Your OTP is {otp}. Valid for 2 minutes.")


async def send_delivery_notification(
    user_id: str, delivery_id: str, event: str, extra: dict[str, Any] | None = None
) -> bool:
    from app.models.notification import Notification
    from app.database import get_session_maker

    messages = {
        "assigned": "Your delivery has been assigned to a driver",
        "picked_up": "Your package has been picked up",
        "in_transit": "Your delivery is on its way",
        "delivered": "Your package has been delivered",
        "otp_required": "OTP required for delivery release",
    }
    title = messages.get(event, f"Delivery {event}")
    session_maker = get_session_maker()
    async with session_maker() as db:
        db.add(Notification(user_id=user_id, title=title, message=extra.get("message", "") if extra else "", type="delivery"))
        await db.commit()
    return True
