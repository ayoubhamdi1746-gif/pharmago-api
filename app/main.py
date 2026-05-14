import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.config import settings
from app.api.prescriptions import router as prescriptions_router
from app.api.pharmacist import router as pharmacist_router
from app.api.doctor import router as doctor_router
from app.api.delivery import router as delivery_router
from app.api.patient import router as patient_router
from app.api.driver import router as driver_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.public import router as public_router
from app.exceptions.handlers import EXCEPTION_HANDLERS

logger = structlog.get_logger()


def create_app() -> FastAPI:
    try:
        settings.validate_secure()
    except RuntimeError as e:
        logger.warning("startup.validation_warning", error=str(e))

    app = FastAPI(title="PharmaGo API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://pharmago-front.vercel.app",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    for exc_cls, handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exc_cls, handler)

    @app.get("/health")
    async def health():
        try:
            from app.database import check_db
            db_ok = await check_db()
            return {"status": "ok", "db": "connected" if db_ok else "disconnected"}
        except Exception as e:
            return {"status": "error", "db": "disconnected", "detail": str(e)}

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(prescriptions_router, prefix="/prescriptions", tags=["prescriptions"])
    app.include_router(pharmacist_router, prefix="/pharmacist", tags=["pharmacist"])
    app.include_router(doctor_router, prefix="/doctor", tags=["doctor"])
    app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
    app.include_router(patient_router, prefix="/patient", tags=["patient"])
    app.include_router(driver_router, prefix="/driver", tags=["driver"])
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(billing_router, prefix="/billing", tags=["billing"])
    app.include_router(public_router, prefix="/public", tags=["public"])

    if settings.DEV_MODE:
        from app.api.dev import router as dev_router
        app.include_router(dev_router, prefix="/dev", tags=["dev"])

    return app


app = create_app()
