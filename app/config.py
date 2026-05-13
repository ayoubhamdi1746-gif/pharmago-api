from pydantic_settings import BaseSettings


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
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    FRONTEND_URL: str = "http://localhost:3000"
    DEV_MODE: bool = False
    KONNECT_API_KEY: str = ""
    KONNECT_WALLET_ID: str = ""
    FLOUCI_APP_TOKEN: str = ""
    FLOUCI_APP_SECRET: str = ""

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


settings = Settings()
