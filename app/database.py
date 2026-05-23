import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text, TypeDecorator, String
from sqlalchemy.orm import DeclarativeBase
import structlog
from app.config import settings


class StrUUID(TypeDecorator):
    """UUID column that accepts Python str values and stores as native PG UUID"""
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID())
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "postgresql":
            if isinstance(value, str):
                return uuid.UUID(value)
            return value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "postgresql":
            return str(value)
        return value

logger = structlog.get_logger()

_engine = None
_async_session_maker = None


def _async_url() -> str:
    url = settings.DATABASE_URL
    if "sqlite" in url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _async_url(),
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_maker():
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_maker


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    maker = get_session_maker()
    async with maker() as session:
        yield session


async def check_db() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("db.check_failed", error=str(e))
        return False


VALID_TABLES = frozenset({"users", "prescriptions", "pharmacy_profiles", "password_reset_otps", "vetted_drivers"})
VALID_COLUMNS = frozenset({
    "updated_at", "full_name", "is_verified",
    "patient_id", "pharmacy_id", "image_url", "medications",
    "status", "risk_level", "pharmacist_note",
    "user_id", "pharmacy_name", "city", "address", "phone", "logo_url",
    "pharmacist_license_hash",
})


async def auto_migrate():
    """Auto-migration: creates missing columns in existing tables"""
    logger.info("db.auto_migration_starting")
    
    COLUMNS_TO_ADD = [
        ("users", "updated_at", "TIMESTAMP"),
        ("users", "full_name", "VARCHAR(255)"),
        ("users", "is_verified", "BOOLEAN DEFAULT FALSE"),
        ("prescriptions", "patient_id", "VARCHAR(36)"),
        ("prescriptions", "pharmacy_id", "VARCHAR(36)"),
        ("prescriptions", "image_url", "TEXT"),
        ("prescriptions", "medications", "JSONB"),
        ("prescriptions", "status", "VARCHAR(20) DEFAULT 'pending'"),
        ("prescriptions", "risk_level", "VARCHAR(20) DEFAULT 'low'"),
        ("prescriptions", "pharmacist_note", "TEXT"),
        ("pharmacy_profiles", "user_id", "VARCHAR(36)"),
        ("pharmacy_profiles", "pharmacy_name", "VARCHAR(200)"),
        ("pharmacy_profiles", "city", "VARCHAR(100)"),
        ("pharmacy_profiles", "address", "TEXT"),
        ("pharmacy_profiles", "phone", "VARCHAR(20)"),
        ("pharmacy_profiles", "logo_url", "TEXT"),
        ("pharmacy_profiles", "is_verified", "BOOLEAN DEFAULT FALSE"),
        ("users", "pharmacist_license_hash", "VARCHAR(64)"),
        ("vetted_drivers", "user_id", "VARCHAR(36)"),
    ]
    
    for table, column, col_type in COLUMNS_TO_ADD:
        if table not in VALID_TABLES or column not in VALID_COLUMNS:
            logger.warning("db.column_skipped_invalid", table=table, column=column)
            continue
        try:
            async with get_engine().begin() as conn:
                result = await conn.execute(
                    text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
                    {"t": table, "c": column},
                )
                if not result.scalar():
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    logger.info("db.column_added", table=table, column=column)
        except Exception as e:
            logger.debug("db.column_check_error", table=table, column=column, error=str(e))
    
    logger.info("db.auto_migration_complete")
