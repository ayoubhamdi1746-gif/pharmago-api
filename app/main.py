from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.config import settings
from app.database import Base, engine, check_db, AsyncSessionLocal
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_secure()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.services.auth_service import hash_password
    from app.models.user import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is None:
            import hashlib, uuid
            from datetime import datetime, timedelta
            from decimal import Decimal
            from app.models.patient import MedicalRecord
            from app.models.pharmacy import LicensedPharmacist, LethalRiskSubstance, ControlledSubstance
            from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
            from app.models.delivery import VettedDriver
            from app.models.billing import PharmacySubscription, SubscriptionPlan

            pharm_hash = hashlib.sha256(b"pharmacist-demo-lic").hexdigest()
            doctor_hash = hashlib.sha256(b"doctor-demo-lic").hexdigest()
            driver_hash = hashlib.sha256(b"driver-demo-token").hexdigest()
            patient_token = "patient-demo-ref"
            admin_key = "admin-demo-key"
            pharmacy_id = uuid.uuid4()

            session.add(PharmacySubscription(
                id=uuid.uuid4(), pharmacy_id=pharmacy_id,
                pharmacy_name="Pharmacie Centrale", city="Tunis",
                responsible_name="Ahmed Al-Farisi", plan=SubscriptionPlan.PRO,
                price_tnd=Decimal("450.00"),
                started_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(days=365),
                is_active=True, delivery_count_this_month=0, delivery_limit=None,
                total_delivery_earnings=Decimal("0.00"),
            ))
            session.add(User(username="patient", role="patient", identity_id=patient_token, hashed_password=hash_password("demo"), is_active=True))
            session.add(User(username="pharmacist", role="pharmacist", identity_id=pharm_hash, hashed_password=hash_password("demo"), is_active=True, pharmacy_id=str(pharmacy_id), city="Tunis"))
            session.add(User(username="doctor", role="doctor", identity_id=doctor_hash, hashed_password=hash_password("demo"), is_active=True))
            session.add(User(username="driver", role="driver", identity_id=driver_hash, hashed_password=hash_password("demo"), is_active=True))
            session.add(User(username="admin", role="admin", identity_id=admin_key, hashed_password=hash_password("demo"), is_active=True))
            session.add(MedicalRecord(reference_token=patient_token, patient_weight_kg=70.0, blood_type="A+", allergies="Penicillin"))
            session.add(LicensedPharmacist(pharmacist_license_hash=pharm_hash, full_name_encrypted=b"Ahmed Al-Farisi (seed)", is_active=True))
            session.add(VettedDriver(driver_token_hash=driver_hash, issuing_pharmacy_id=pharmacy_id, license_issued_at=datetime.utcnow() - timedelta(days=30), license_expires_at=datetime.utcnow() + timedelta(days=335), is_active=True))
            session.add(LethalRiskSubstance(dpm_code="LETHAL01", generic_name="Tramadol", ld50_threshold_mg_per_kg=10.0, suicide_risk_flag=False))
            session.add(LethalRiskSubstance(dpm_code="LETHAL02", generic_name="Sedative-Y", ld50_threshold_mg_per_kg=5.0, suicide_risk_flag=True, single_course_limit=10))
            session.add(ControlledSubstance(dpm_code="SAFE01", generic_name="Paracetamol", requires_dual_approval=False))
            session.add(ControlledSubstance(dpm_code="SAFE02", generic_name="Amoxicillin", requires_dual_approval=False))

            now = datetime.utcnow()
            pid1 = uuid.uuid4(); pid2 = uuid.uuid4(); pid3 = uuid.uuid4(); pid4 = uuid.uuid4()
            session.add(Prescription(id=pid1, patient_reference_token=patient_token, doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456", items=[{"dpm_code": "SAFE01", "dose_mg": 500, "quantity": 1}], pharmacy_id=str(pharmacy_id)))
            session.add(PrescriptionVerification(prescription_id=pid1, status="PENDING"))
            session.add(Prescription(id=pid2, patient_reference_token=patient_token, doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456", items=[{"dpm_code": "LETHAL01", "dose_mg": 100, "quantity": 3}], pharmacy_id=str(pharmacy_id)))
            session.add(PrescriptionVerification(prescription_id=pid2, status="HIGH_RISK_PENDING"))
            session.add(DoctorConfirmationRequest(prescription_id=pid2, doctor_license_hash=doctor_hash, requested_at=now, expires_at=now + timedelta(hours=4), status="AWAITING"))
            session.add(Prescription(id=pid3, patient_reference_token=patient_token, doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456", items=[{"dpm_code": "SAFE02", "dose_mg": 250, "quantity": 2}], pharmacy_id=str(pharmacy_id)))
            session.add(PrescriptionVerification(prescription_id=pid3, status="VERIFIED", pharmacist_license_hash=pharm_hash, verified_at=now))
            session.add(Prescription(id=pid4, patient_reference_token=patient_token, doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456", items=[{"dpm_code": "SAFE02", "dose_mg": 250, "quantity": 1}], pharmacy_id=str(pharmacy_id)))
            session.add(PrescriptionVerification(prescription_id=pid4, status="DISPENSED", pharmacist_license_hash=pharm_hash, verified_at=now, dispensed_at=now))
            await session.commit()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="PharmaGo API", lifespan=lifespan, redirect_slashes=False)

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
        db_ok = await check_db()
        return {"status": "ok", "db": "connected" if db_ok else "disconnected"}

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
