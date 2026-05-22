import os, base64
import structlog
from pydantic_settings import BaseSettings

logger = structlog.get_logger()


def _gen_secret(name: str, default: str) -> str:
    if len(default) >= 32:
        return default
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    logger.warning(f"{name} not set — generated ephemeral key (valid until restart)")
    return key


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./pharmago_demo.db"
    FERNET_KEY: str = ""
    HMAC_SECRET: str = ""
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DOCTOR_TOKEN_TTL_HOURS: int = 4
    DELIVERY_TICKET_TTL_MINUTES: int = 60
    SAFETY_LD50_FACTOR: float = 0.25
    MIN_ASSIGN_DELAY_SEC: float = 0.0
    MAX_ASSIGN_DELAY_SEC: float = 480.0
    FULFILL_RATE_LIMIT: str = "5/minute"
    FRONTEND_URL: str = "http://localhost:3000"
    DEV_MODE: bool = False
    REDIS_URL: str = ""
    SENTRY_DSN: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    DEFAULT_LOCALE: str = "en"
    KONNECT_API_KEY: str = ""
    KONNECT_WALLET_ID: str = ""
    FLOUCI_APP_TOKEN: str = ""
    FLOUCI_APP_SECRET: str = ""
    SETUP_KEY: str = ""

    class Config:
        env_file = ".env"

    def model_post_init(self, __context) -> None:
        self.HMAC_SECRET = _gen_secret("HMAC_SECRET", self.HMAC_SECRET)
        self.JWT_SECRET = _gen_secret("JWT_SECRET", self.JWT_SECRET)
        self.FERNET_KEY = _gen_secret("FERNET_KEY", self.FERNET_KEY)

    def validate_secure(self) -> None:
        if not self.DEV_MODE:
            if not self.KONNECT_API_KEY:
                logger.warning("KONNECT_API_KEY not set — payment webhooks will fail")
            if not self.KONNECT_WALLET_ID:
                logger.warning("KONNECT_WALLET_ID not set — payment webhooks will fail")


settings = Settings()
