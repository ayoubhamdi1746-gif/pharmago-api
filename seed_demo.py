"""
Seed script — يملأ قاعدة البيانات ببيانات تجريبية لكل دور.
تشغيل:
    python seed_demo.py
"""

import asyncio, hashlib, uuid
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.config import settings
from app.models.patient import MedicalRecord
from app.models.pharmacy import LicensedPharmacist, LethalRiskSubstance, ControlledSubstance
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.delivery import VettedDriver
from app.models.user import User
from app.services.auth_service import hash_password

# ── ثوابت الأدوار ──────────────────────────────────────────────────────────
PATIENT_TOKEN  = "patient-demo-ref"
PHARM_HASH     = "135ef9255b5de7aac9cd185c31053780fb3f2652e42d653bd43fc11a468daacf"
DOCTOR_HASH    = "9fc16bd59f7afdf4804ceb3e648945e8f417db94dbe8148b8be7fb84e8095bbc"
DRIVER_TOKEN   = "a670f01fbcc6ce4ba9c4a1092d36ae50f6fbee8564cbceda034416dc6dd7f3a4"
ADMIN_KEY      = "admin-demo-key"


async def seed():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # ── USERS (لـ /auth/login) ──────────────────────────────────────
        session.add(User(username="patient",   role="patient",   identity_id=PATIENT_TOKEN, hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="pharmacist", role="pharmacist", identity_id=PHARM_HASH,   hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="doctor",    role="doctor",    identity_id=DOCTOR_HASH,   hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="driver",    role="driver",    identity_id=DRIVER_TOKEN,  hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="admin",     role="admin",     identity_id=ADMIN_KEY,     hashed_password=hash_password("demo"), is_active=True))

        # ── PATIENT ──────────────────────────────────────────────────────
        session.add(MedicalRecord(
            reference_token=PATIENT_TOKEN,
            patient_weight_kg=70.0,
            blood_type="A+",
            allergies="لا يوجد",
        ))

        # ── PHARMACIST ───────────────────────────────────────────────────
        session.add(LicensedPharmacist(
            pharmacist_license_hash=PHARM_HASH,
            full_name_encrypted=b"Ahmed Al-Farisi (demo)",
            is_active=True,
        ))

        # ── DRIVER ───────────────────────────────────────────────────────
        session.add(VettedDriver(
            driver_token_hash=DRIVER_TOKEN,
            issuing_pharmacy_id=uuid.uuid4(),
            license_issued_at=datetime.utcnow() - timedelta(days=30),
            license_expires_at=datetime.utcnow() + timedelta(days=335),
            is_active=True,
        ))

        # ── LETHAL RISK / CONTROLLED SUBSTANCES ─────────────────────────
        session.add(LethalRiskSubstance(
            dpm_code="LETHAL01", generic_name="Tramadol",
            ld50_threshold_mg_per_kg=10.0, suicide_risk_flag=False,
        ))
        session.add(LethalRiskSubstance(
            dpm_code="LETHAL02", generic_name="Sedative-Y",
            ld50_threshold_mg_per_kg=5.0, suicide_risk_flag=True,
            single_course_limit=10,
        ))
        session.add(ControlledSubstance(
            dpm_code="SAFE01", generic_name="Paracetamol",
            requires_dual_approval=False,
        ))
        session.add(ControlledSubstance(
            dpm_code="SAFE02", generic_name="Amoxicillin",
            requires_dual_approval=False,
        ))

        # ── PRESCRIPTION 1 - PENDING: Paracetamol 500mg ──────────────────
        pid1 = uuid.uuid4()
        session.add(Prescription(
            id=pid1,
            patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "SAFE01", "dose_mg": 500, "quantity": 1}],
        ))
        session.add(PrescriptionVerification(
            prescription_id=pid1, status="PENDING",
        ))

        # ── PRESCRIPTION 2 - DISPENSED: Amoxicillin 250mg ────────────────
        pid2 = uuid.uuid4()
        session.add(Prescription(
            id=pid2,
            patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "SAFE02", "dose_mg": 250, "quantity": 2}],
        ))
        session.add(PrescriptionVerification(
            prescription_id=pid2, status="DISPENSED",
            pharmacist_license_hash=PHARM_HASH,
            verified_at=datetime.utcnow(),
            dispensed_at=datetime.utcnow(),
        ))

        # ── PRESCRIPTION 3 - HIGH_RISK_PENDING: Tramadol 100mg ───────────
        pid3 = uuid.uuid4()
        session.add(Prescription(
            id=pid3,
            patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "LETHAL01", "dose_mg": 100, "quantity": 3}],
        ))
        session.add(PrescriptionVerification(
            prescription_id=pid3, status="HIGH_RISK_PENDING",
        ))
        now = datetime.utcnow()
        session.add(DoctorConfirmationRequest(
            prescription_id=pid3,
            doctor_license_hash=DOCTOR_HASH,
            requested_at=now,
            expires_at=now + timedelta(hours=4),
            status="AWAITING",
        ))

        await session.commit()

    await engine.dispose()
    print("[OK] Demo database seeded successfully!")
    print(f"  Database: {settings.DATABASE_URL}")
    print()


def show_guide():
    print("=" * 60)
    print("  PharmaGo Demo — دليل الاستخدام")
    print("=" * 60)
    print()
    print("  Swagger UI : http://localhost:8000/docs")
    print()
    print("  ─── تسجيل الدخول (JWT) ───")
    print()
    print("  POST /auth/login  JSON: {'username': 'patient', 'password': 'demo'}")
    print()
    print("  المستخدمون:")
    print("    patient   / demo")
    print("    pharmacist / demo")
    print("    doctor    / demo")
    print("    driver    / demo")
    print("    admin     / demo")
    print()
    print("  ─── Dev Login (يرجع JWT) ───")
    print("  POST /dev/login  JSON: {'role': 'PATIENT'}")
    print()
    print("  ─── معرفات الوصفات للتجربة ───")
    print("  (اطّلع على السكريبت أو راجع قاعدة البيانات)")
    print()
    print("  ملاحظة: لا تنس تفعيل Swagger Authorize")
    print("  يدوياً عبر إضافة الرؤوس أعلاه في كل طلب")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
    show_guide()
