"""
seed.py — ينشئ قاعدة البيانات ببيانات تجريبية شاملة.

الاستخدام:
    python seed.py

يُنشئ:
  - مستخدماً واحداً لكل دور (PATIENT, PHARMACIST, DOCTOR, DRIVER, ADMIN)
  - وصفة في كل حالة (PENDING, HIGH_RISK_PENDING, VERIFIED, DISPENSED)
  - مواد خاضعة للرقابة والاختبار
  - يطبع الرؤوس الجاهزة للاستخدام
"""

import asyncio, hashlib, uuid
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.config import settings
from app.models.patient import MedicalRecord
from app.models.pharmacy import LicensedPharmacist, LethalRiskSubstance, ControlledSubstance
from app.models.prescription import Prescription, PrescriptionVerification, DoctorConfirmationRequest
from app.models.delivery import VettedDriver
from app.models.billing import PharmacySubscription, SubscriptionPlan
from app.models.user import User
from app.services.auth_service import hash_password

# ── Tokens متطابقة مع /dev/login ──────────────────────────────────────────
PATIENT_TOKEN = "patient-demo-ref"
PHARM_HASH    = hashlib.sha256(b"pharmacist-demo-lic").hexdigest()
DOCTOR_HASH   = hashlib.sha256(b"doctor-demo-lic").hexdigest()
DRIVER_HASH   = hashlib.sha256(b"driver-demo-token").hexdigest()
ADMIN_KEY     = "admin-demo-key"


async def seed():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # ── Seed PharmacySubscription (for multi-tenant isolation) ──────
        pharmacy_id = uuid.uuid4()
        session.add(PharmacySubscription(
            id=uuid.uuid4(),
            pharmacy_id=pharmacy_id,
            pharmacy_name="Pharmacie Centrale",
            city="Tunis",
            responsible_name="Ahmed Al-Farisi",
            plan=SubscriptionPlan.PRO,
            price_tnd=Decimal("450.00"),
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=365),
            is_active=True,
            delivery_count_this_month=0,
            delivery_limit=None,
            total_delivery_earnings=Decimal("0.00"),
        ))

        # ── USERS (لـ /auth/login) ──────────────────────────────────────
        session.add(User(username="patient",   role="patient",   identity_id=PATIENT_TOKEN, hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="pharmacist", role="pharmacist", identity_id=PHARM_HASH,   hashed_password=hash_password("demo"), is_active=True, pharmacy_id=str(pharmacy_id), city="Tunis", pharmacist_license_hash=PHARM_HASH))
        session.add(User(username="doctor",    role="doctor",    identity_id=DOCTOR_HASH,   hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="driver",    role="driver",    identity_id=DRIVER_HASH,   hashed_password=hash_password("demo"), is_active=True))
        session.add(User(username="admin",     role="admin",     identity_id=ADMIN_KEY,     hashed_password=hash_password("demo"), is_active=True))

        # ── PATIENT ──────────────────────────────────────────────────────
        session.add(MedicalRecord(
            reference_token=PATIENT_TOKEN,
            patient_weight_kg=70.0,
            blood_type="A+",
            allergies="Penicillin",
        ))

        # ── PHARMACIST ───────────────────────────────────────────────────
        session.add(LicensedPharmacist(
            pharmacist_license_hash=PHARM_HASH,
            full_name_encrypted=b"Ahmed Al-Farisi (seed)",
            is_active=True,
        ))

        # ── DRIVER ───────────────────────────────────────────────────────
        session.add(VettedDriver(
            driver_token_hash=DRIVER_HASH,
            issuing_pharmacy_id=pharmacy_id,
            license_issued_at=datetime.utcnow() - timedelta(days=30),
            license_expires_at=datetime.utcnow() + timedelta(days=335),
            is_active=True,
        ))

        # ── Controlled + Lethal substances ───────────────────────────────
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

        now = datetime.utcnow()

        # ── 1. PENDING - Paracetamol 500mg ───────────────────────────────
        pid1 = uuid.uuid4()
        session.add(Prescription(id=pid1, patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "SAFE01", "dose_mg": 500, "quantity": 1}],
            pharmacy_id=str(pharmacy_id)))
        session.add(PrescriptionVerification(prescription_id=pid1, status="PENDING"))

        # ── 2. HIGH_RISK_PENDING - Tramadol 100mg ───────────────────────
        pid2 = uuid.uuid4()
        session.add(Prescription(id=pid2, patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "LETHAL01", "dose_mg": 100, "quantity": 3}],
            pharmacy_id=str(pharmacy_id)))
        session.add(PrescriptionVerification(prescription_id=pid2, status="HIGH_RISK_PENDING"))
        session.add(DoctorConfirmationRequest(
            prescription_id=pid2, doctor_license_hash=DOCTOR_HASH,
            requested_at=now, expires_at=now + timedelta(hours=4),
            status="AWAITING"))

        # ── 3. VERIFIED - Amoxicillin 250mg ──────────────────────────────
        pid3 = uuid.uuid4()
        session.add(Prescription(id=pid3, patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "SAFE02", "dose_mg": 250, "quantity": 2}],
            pharmacy_id=str(pharmacy_id)))
        session.add(PrescriptionVerification(
            prescription_id=pid3, status="VERIFIED",
            pharmacist_license_hash=PHARM_HASH,
            verified_at=now))

        # ── 4. DISPENSED ────────────────────────────────────────────────
        pid4 = uuid.uuid4()
        session.add(Prescription(id=pid4, patient_reference_token=PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali", doctor_phone="+21698123456",
            items=[{"dpm_code": "SAFE02", "dose_mg": 250, "quantity": 1}],
            pharmacy_id=str(pharmacy_id)))
        session.add(PrescriptionVerification(
            prescription_id=pid4, status="DISPENSED",
            pharmacist_license_hash=PHARM_HASH,
            verified_at=now, dispensed_at=now))

        await session.commit()

    await engine.dispose()
    print("Database seeded successfully!")
    print()


def print_guide():
    L = "=" * 64
    print(L)
    print("  PharmaGo Demo - Ready-to-use Headers")
    print(L)
    print()
    print("  Swagger UI : http://localhost:8000/docs")
    print("  Dev Login  : POST /dev/login  (see body below)")
    print("  Auth Login : POST /auth/login  {'username': 'patient', 'password': 'demo'}")
    print()
    print("  -- Demo users for /auth/login --")
    print()
    users = [
        ("patient",   "demo"),
        ("pharmacist", "demo"),
        ("doctor",    "demo"),
        ("driver",    "demo"),
        ("admin",     "demo"),
    ]
    for username, pw in users:
        print(f"  {username:12s}  password: {pw}")
    print()
    print("  -- Dev login body --")
    print('  POST /dev/login')
    print('  {"role": "PATIENT"}')
    print()
    print("  -- Prescription IDs --")
    print("  Run: sqlite3 pharmago_demo.db \"SELECT id, status FROM prescription_verifications;\"")
    print()
    print("  -- Doctor confirm helper --")
    print("  Use POST /dev/login with role=DOCTOR, then call")
    print("  /prescriptions/{id}/doctor-confirm with the signed_token")
    print("  generated via the /dev/login response.")
    print(L)


if __name__ == "__main__":
    asyncio.run(seed())
    print_guide()
