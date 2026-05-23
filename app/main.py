import structlog
from fastapi import FastAPI, Request
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
from app.api.super_admin import router as super_admin_router

from app.api.notifications import router as notifications_router
from app.api.delivery_tracking import router as delivery_tracking_router
from app.api.reviews import router as reviews_router
from app.api.support import router as support_router
from app.api.pharmacy_analytics import router as pharmacy_analytics_router
from app.api.marketplace import router as marketplace_router
from app.api.smart_inventory import router as smart_inventory_router
from app.exceptions.handlers import EXCEPTION_HANDLERS
from app.services.sentry_setup import init_sentry
from app.services.i18n_service import get_locale

logger = structlog.get_logger()


def create_app() -> FastAPI:
    try:
        settings.validate_secure()
    except Exception as e:
        logger.warning("app.config_invalid", error=str(e))

    app = FastAPI(title="PharmaGo API", version="2.0.0", description="Enterprise pharmacy management platform — Tunisian market")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://pharmago-front.vercel.app",
            "http://localhost:3000",
            settings.FRONTEND_URL,
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def i18n_middleware(request: Request, call_next):
        locale = get_locale(request)
        response = await call_next(request)
        response.headers["X-Content-Language"] = locale
        return response

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        path = request.url.path
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; img-src 'self' data:; font-src 'self' cdn.jsdelivr.net fonts.gstatic.com; connect-src 'self'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

    init_sentry()

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    for exc_cls, handler in EXCEPTION_HANDLERS.items():
        app.add_exception_handler(exc_cls, handler)

    @app.get("/health")
    async def health():
        try:
            from app.database import check_db
            db_ok = await check_db()
            return {"status": "ok", "db": "connected" if db_ok else "disconnected", "version": "1.0.0"}
        except Exception as e:
            return {"status": "error", "db": "disconnected", "detail": str(e), "version": "1.0.0"}

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
    app.include_router(super_admin_router, prefix="/admin/super", tags=["super_admin"])
    app.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
    app.include_router(delivery_tracking_router, prefix="/delivery", tags=["delivery"])
    app.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
    app.include_router(support_router, prefix="/support", tags=["support"])
    app.include_router(pharmacy_analytics_router, prefix="/pharmacy", tags=["pharmacy"])
    app.include_router(marketplace_router, prefix="/marketplace", tags=["marketplace"])
    app.include_router(smart_inventory_router, prefix="/pharmacy/inventory", tags=["pharmacy"])

    @app.get("/debug/startup")
    async def debug_startup():
        from app.database import get_engine, get_session_maker
        from sqlalchemy import text, select
        from app.config import settings
        from app.models.user import User
        import traceback as tb_mod
        result = []
        try:
            async with get_engine().connect() as conn:
                rows = await conn.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'"))
                tables = [r[0] for r in rows.fetchall()]
                result.append({"engine_ok": True, "tables": tables})
        except Exception as e:
            result.append({"engine_ok": False, "error": str(e), "tb": tb_mod.format_exc()})
        try:
            from app.services.auth_service import hash_password, verify_password, create_access_token
            pw = hash_password("test123")
            ok = verify_password("test123", pw)
            token = create_access_token("user123", "patient", "id123")
            result.append({"auth_ok": True, "verify_pass": ok, "token_prefix": token[:20]})
        except Exception as e:
            result.append({"auth_error": str(e), "tb": tb_mod.format_exc()})
        try:
            async with get_engine().begin() as conn:
                existing = set()
                rows = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))
                for r in rows: existing.add(r[0])
                all_cols = ["pharmacist_license_hash", "email", "hashed_password", "role", "identity_id", "is_active"]
                missing = [c for c in all_cols if c not in existing]
                for col in missing:
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR(255)"))
                result.append({"fixed_columns": f"added {missing}" if missing else "none needed"})
        except Exception as e:
            result.append({"fixed_columns_error": str(e)})
        try:
            async with get_engine().connect() as conn:
                rows = await conn.execute(text("SELECT table_name, column_name, udt_name FROM information_schema.columns WHERE column_name='id' AND table_schema='public'"))
                col_info = {}
                for r in rows: col_info[r[0]] = r[2]
                result.append({"col_types": col_info})
        except Exception as e:
            result.append({"col_types_error": str(e)})
        try:
            async with get_engine().connect() as conn:
                rows = await conn.execute(text("SELECT table_name, column_name, udt_name FROM information_schema.columns WHERE column_name IN ('user_id','driver_id','pharmacy_id','patient_id','actor_id','author_id') AND table_schema='public'"))
                fk_info = {}
                for r in rows:
                    key = f"{r[0]}.{r[1]}"
                    fk_info[key] = r[2]
                result.append({"fk_col_types": fk_info})
        except Exception as e:
            result.append({"fk_col_types_error": str(e)})
        try:
            maker = get_session_maker()
            async with maker() as session:
                r = await session.execute(select(User).where(User.username == "__debug_test__"))
                user = r.scalar_one_or_none()
                result.append({"session_ok": True, "user_found": user is not None})
        except Exception as e:
            result.append({"session_error": str(e), "tb": tb_mod.format_exc()[:200]})
        result.append({"db_url_prefix": settings.DATABASE_URL[:30] + "..." if settings.DATABASE_URL else "NOT SET"})
        result.append({"jwt_secret_set": bool(settings.JWT_SECRET), "jwt_secret_len": len(settings.JWT_SECRET)})
        return result

    # Dev routes available only in DEV_MODE
    if settings.DEV_MODE:
        try:
            from app.api.dev import router as dev_router
            app.include_router(dev_router, prefix="/dev", tags=["dev"])
        except ImportError:
            pass

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        import time
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info("request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=round(duration * 1000))
        return response

    @app.on_event("startup")
    async def startup():
        try:
            from app.database import auto_migrate, get_engine, Base
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await auto_migrate()
            logger.info("app.startup_complete")
        except Exception as e:
            logger.warning("app.startup_error", error=str(e))

    @app.on_event("shutdown")
    async def shutdown():
        try:
            from app.database import get_engine
            engine = get_engine()
            await engine.dispose()
            from app.api.delivery_tracking import ACTIVE_STREAMS
            ACTIVE_STREAMS.clear()
            logger.info("app.shutdown_complete")
        except Exception as e:
            logger.warning("app.shutdown_error", error=str(e))

    return app


app = create_app()