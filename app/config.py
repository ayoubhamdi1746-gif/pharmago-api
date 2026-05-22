import structlog
from pydantic_settings import BaseSettings

logger = structlog.get_logger()


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

    def validate_secure(self) -> None:
        if len(self.HMAC_SECRET) < 32:
            raise RuntimeError(
                f"HMAC_SECRET must be at least 32 characters (got {len(self.HMAC_SECRET)})"
            )
        if len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                f"JWT_SECRET must be at least 32 characters (got {len(self.JWT_SECRET)})"
            )
        if not self.DEV_MODE:
            if not self.FERNET_KEY:
                raise RuntimeError("FERNET_KEY is required in production")
            if not self.KONNECT_API_KEY:
                logger.warning("KONNECT_API_KEY not set — payment webhooks will fail")
            if not self.KONNECT_WALLET_ID:
                logger.warning("KONNECT_WALLET_ID not set — payment webhooks will fail")


settings = Settings()
