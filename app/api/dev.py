import uuid
import structlog
from datetime import datetime, timedelta
import hashlib
import os
@router.get("/migrate-users")
@limiter.limit("1/minute")
async def dev_migrate_users(request: Request):
    secret = request.headers.get("X-Setup-Key")
    if secret != "PHARMAGO_SETUP_2026":
        raise HTTPException(403, "Forbidden")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise HTTPException(500, "DATABASE_URL not set")

    try:
        import psycopg2
    except ImportError:
        raise HTTPException(500, "psycopg2 not installed")

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS pharmacy_id VARCHAR(36)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
    ]

    results = []
    for sql in migrations:
        try:
            cur.execute(sql)
            results.append({"sql": sql[:40], "status": "ok"})
        except Exception as e:
            results.append({"sql": sql[:40], "status": "error", "error": str(e)})

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
    columns = [r[0] for r in cur.fetchall()]

    cur.close()
    conn.close()
    return APIResponse(status="ok", message="DELETE /dev/migrate-users after use", data={"migrations": results, "columns": columns}, ref=new_ref())
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
from app.api.deps import get_db
from app.services.auth_service import hash_password
from app.schemas.common import APIResponse
from app.models.user import User
from app.logging.cfg import new_ref
from app.config import settings
from app.limiter import limiter
from app.models.billing import PharmacySubscription, SubscriptionPlan

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def _hash(p: str) -> str:
    return pwd_context.hash(p)

router = APIRouter()
logger = structlog.get_logger()


class LoginRequest(BaseModel):
    role: str = Field(description="One of: PATIENT, PHARMACIST, DOCTOR, DRIVER, ADMIN")


class LoginResponse(BaseModel):
    role: str
    headers: dict
    description: str = "انسخ هذه الرؤوس واستخدمها في Swagger UI أو أي عميل API"


ROLE_IDENTITY_MAP = {
    "PATIENT":   "patient-demo-ref",
    "PHARMACIST": "135ef9255b5de7aac9cd185c31053780fb3f2652e42d653bd43fc11a468daacf",
    "DOCTOR":    "9fc16bd59f7afdf4804ceb3e648945e8f417db94dbe8148b8be7fb84e8095bbc",
    "DRIVER":    "a670f01fbcc6ce4ba9c4a1092d36ae50f6fbee8564cbceda034416dc6dd7f3a4",
    "ADMIN":     "admin-demo-key",
}


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def dev_login(body: LoginRequest, request: Request):
    role = body.role.upper()
    identity_id = ROLE_IDENTITY_MAP.get(role)
    if not identity_id:
        valid = ", ".join(ROLE_IDENTITY_MAP)
        raise HTTPException(400, f"Invalid role. Valid: {valid}")

    role_str = role.lower()
    token = create_access_token("dev-" + role, role_str, identity_id)
    return LoginResponse(
        role=role,
        headers={"Authorization": f"Bearer {token}"},
    )


DEMO_PATIENT_TOKEN = "patient-demo-ref"
DEMO_PHARMACIST_HASH = "135ef9255b5de7aac9cd185c31053780fb3f2652e42d653bd43fc11a468daacf"

DEMO_PRESCRIPTIONS = [
    {
        "label": "Paracetamol 500mg",
        "dpm_code": "SAFE01",
        "dose_mg": 500,
        "quantity": 1,
        "status": "PENDING",
    },
    {
        "label": "Tramadol 100mg",
        "dpm_code": "LETHAL01",
        "dose_mg": 100,
        "quantity": 3,
        "status": "HIGH_RISK_PENDING",
    },
    {
        "label": "Amoxicillin 250mg",
        "dpm_code": "SAFE02",
        "dose_mg": 250,
        "quantity": 2,
        "status": "VERIFIED",
    },
]


@router.post("/seed-pharmacist-queue")
@limiter.limit("5/minute")
async def dev_seed_pharmacist_queue(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    existing = await db.execute(select(PrescriptionVerification))
    if existing.scalars().first():
        return APIResponse(
            status="ok",
            message="Demo data already seeded",
            data={"prescriptions": []},
            ref=ref,
        )

    mr = await db.execute(
        select(MedicalRecord).where(MedicalRecord.reference_token == DEMO_PATIENT_TOKEN)
    )
    if not mr.scalar_one_or_none():
        db.add(MedicalRecord(
            reference_token=DEMO_PATIENT_TOKEN,
            patient_weight_kg=70.0,
            blood_type="O+",
            allergies="None",
        ))
        await db.commit()

    results = []
    for demo in DEMO_PRESCRIPTIONS:
        presc = Prescription(
            patient_reference_token=DEMO_PATIENT_TOKEN,
            doctor_name="Dr. Ahmed Ben Ali",
            doctor_phone="+21698123456",
            doctor_email="dr.bensalem@example.com",
            items=[{
                "dpm_code": demo["dpm_code"],
                "dose_mg": demo["dose_mg"],
                "quantity": demo["quantity"],
            }],
        )
        db.add(presc)
        await db.commit()
        await db.refresh(presc)

        pv_kwargs = {
            "prescription_id": presc.id,
            "status": demo["status"],
        }
        if demo["status"] == "VERIFIED":
            pv_kwargs["pharmacist_license_hash"] = DEMO_PHARMACIST_HASH
            pv_kwargs["verified_at"] = datetime.utcnow()

        pv = PrescriptionVerification(**pv_kwargs)
        db.add(pv)

        if demo["status"] == "HIGH_RISK_PENDING":
            dcr = DoctorConfirmationRequest(
                prescription_id=presc.id,
                doctor_license_hash="",
                expires_at=datetime.utcnow() + timedelta(hours=4),
            )
            db.add(dcr)

        await db.commit()
        results.append({
            "prescription_id": str(presc.id),
            "label": demo["label"],
            "status": demo["status"],
        })

    logger.info("Pharmacist queue seeded", ref=ref, count=len(results))
    return APIResponse(
        status="ok",
        message="Données de démo chargées",
        data={"prescriptions": results},
        ref=ref,
    )


@router.post("/seed-doctor")
@limiter.limit("5/minute")
async def dev_seed_doctor(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    existing = await db.execute(select(DoctorConfirmationRequest))
    if existing.scalars().first():
        return APIResponse(status="ok", message="Doctor demo data already seeded", ref=ref)

    for demo in DEMO_PRESCRIPTIONS:
        presc = Prescription(
            patient_reference_token=DEMO_PATIENT_TOKEN,
            items=[{
                "dpm_code": demo["dpm_code"],
                "dose_mg": demo["dose_mg"],
                "quantity": demo["quantity"],
            }],
            doctor_name="Dr. Ahmed Ben Ali",
            doctor_phone="+21698123456",
            doctor_email="dr.bensali@example.com",
        )
        db.add(presc)
        await db.commit()
        await db.refresh(presc)

        pv = PrescriptionVerification(prescription_id=presc.id, status=demo["status"])
        db.add(pv)

        if demo["status"] == "HIGH_RISK_PENDING":
            dcr = DoctorConfirmationRequest(
                prescription_id=presc.id,
                doctor_license_hash="9fc16bd59f7afdf4804ceb3e648945e8f417db94dbe8148b8be7fb84e8095bbc",
                expires_at=datetime.utcnow() + timedelta(hours=4),
            )
            db.add(dcr)
        await db.commit()

    logger.info("Doctor dashboard seeded", ref=ref)
    return APIResponse(status="ok", message="Données médecin chargées", data={"count": len(DEMO_PRESCRIPTIONS)}, ref=ref)


@router.post("/seed-driver")
@limiter.limit("5/minute")
async def dev_seed_driver(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    existing = await db.execute(select(DeliveryTicket))
    if existing.scalars().first():
        return APIResponse(status="ok", message="Driver demo data already seeded", ref=ref)

    existing_pv = await db.execute(
        select(PrescriptionVerification).where(PrescriptionVerification.status == "VERIFIED")
    )
    pv = existing_pv.scalars().first()
    if not pv:
        presc = Prescription(
            patient_reference_token=DEMO_PATIENT_TOKEN,
            items=[{"dpm_code": "SAFE01", "dose_mg": 500, "quantity": 1}],
            doctor_name="Dr. Ahmed Ben Salem",
        )
        db.add(presc)
        await db.commit()
        await db.refresh(presc)
        pv = PrescriptionVerification(
            prescription_id=presc.id, status="VERIFIED",
            pharmacist_license_hash=DEMO_PHARMACIST_HASH, verified_at=datetime.utcnow(),
        )
        db.add(pv)
        await db.commit()
        await db.refresh(pv)

    ticket = DeliveryTicket(
        prescription_id=pv.prescription_id,
        pickup_coords="36.8065,10.1815",
        encrypted_dropoff=b"dummy_encrypted_data",
        otp_hash=hashlib.sha256(b"123456").hexdigest(),
        expires_at=datetime.utcnow() + timedelta(hours=2),
        is_fulfilled=False,
        driver_token_hash="a670f01fbcc6ce4ba9c4a1092d36ae50f6fbee8564cbceda034416dc6dd7f3a4",
    )
    db.add(ticket)
    await db.commit()

    logger.info("Driver dashboard seeded", ref=ref)
    return APIResponse(status="ok", message="Données livreur chargées", ref=ref)


@router.post("/seed-admin")
@limiter.limit("5/minute")
async def dev_seed_admin(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    existing = await db.execute(select(PharmacySubscription))
    if existing.scalars().first():
        return APIResponse(status="ok", message="Admin demo data already seeded", ref=ref)

    for plan in SubscriptionPlan:
        started = datetime.utcnow() - timedelta(days=15)
        sub = PharmacySubscription(
            pharmacy_name=f"Pharmacie {plan.value}",
            pharmacy_id=uuid.uuid4(),
            plan=plan,
            price_tnd=PLAN_PRICES[plan],
            started_at=started,
            expires_at=started + timedelta(days=30),
            is_active=True,
            delivery_count_this_month=12 if plan == SubscriptionPlan.STARTER else 45,
            delivery_limit=50 if plan == SubscriptionPlan.STARTER else None,
            total_delivery_earnings=PLAN_PRICES[plan] * 3,
        )
        db.add(sub)
    await db.commit()

    driver_hash = "a670f01fbcc6ce4ba9c4a1092d36ae50f6fbee8564cbceda034416dc6dd7f3a4"
    for i in range(3):
        ticket = DeliveryTicket(
            prescription_id=uuid.uuid4(),
            pickup_coords="36.8065,10.1815",
            encrypted_dropoff=b"dummy",
            otp_hash=hashlib.sha256(f"otp{i}".encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(hours=2),
            is_fulfilled=True,
            driver_token_hash=driver_hash,
        )
        db.add(ticket)
        await db.flush()

        comm = DeliveryCommission(
            delivery_ticket_id=ticket.id,
            commission_amount_tnd=2.50,
            status=CommissionStatus.COLLECTED,
        )
        db.add(comm)

        payout = DriverPayout(
            driver_token_hash=driver_hash,
            delivery_ticket_id=ticket.id,
            amount_tnd=3.00,
            status=DriverPayoutStatus.PAID,
            paid_at=datetime.utcnow(),
        )
        db.add(payout)
    await db.commit()

    logger.info("Admin dashboard seeded", ref=ref)
    return APIResponse(status="ok", message="Données admin chargées", ref=ref)


@router.post("/seed-patient")
@limiter.limit("5/minute")
async def dev_seed_patient(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    existing = await db.execute(
        select(Prescription).where(Prescription.patient_reference_token == DEMO_PATIENT_TOKEN)
    )
    if existing.scalars().first():
        return APIResponse(status="ok", message="Patient demo data already seeded", ref=ref)

    mr = await db.execute(
        select(MedicalRecord).where(MedicalRecord.reference_token == DEMO_PATIENT_TOKEN)
    )
    if not mr.scalar_one_or_none():
        db.add(MedicalRecord(
            reference_token=DEMO_PATIENT_TOKEN,
            patient_weight_kg=70.0,
            blood_type="O+",
            allergies="Pénicilline",
        ))
        await db.commit()

    results = []
    for i, demo in enumerate(DEMO_PRESCRIPTIONS):
        presc = Prescription(
            patient_reference_token=DEMO_PATIENT_TOKEN,
            items=[{"dpm_code": demo["dpm_code"], "dose_mg": demo["dose_mg"], "quantity": demo["quantity"]}],
            doctor_name="Dr. Ahmed Ben Ali",
            doctor_phone="+21698123456",
            doctor_email="dr.bensalem@example.com",
        )
        db.add(presc)
        await db.commit()
        await db.refresh(presc)

        pv = PrescriptionVerification(prescription_id=presc.id, status=demo["status"])
        if demo["status"] == "VERIFIED":
            pv.pharmacist_license_hash = DEMO_PHARMACIST_HASH
            pv.verified_at = datetime.utcnow()

        db.add(pv)

        if demo["status"] == "HIGH_RISK_PENDING":
            dcr = DoctorConfirmationRequest(
                prescription_id=presc.id,
                doctor_license_hash="",
                expires_at=datetime.utcnow() + timedelta(hours=4),
            )
            db.add(dcr)

        await db.commit()
        results.append({"prescription_id": str(presc.id), "label": demo["label"], "status": demo["status"]})

    logger.info("Patient dashboard seeded", ref=ref, count=len(results))
    return APIResponse(status="ok", message="Données patient chargées", data={"prescriptions": results}, ref=ref)


@router.post("/seed-users")
@limiter.limit("5/minute")
async def dev_seed_users(
    request: Request, db: AsyncSession = Depends(get_db),
):
    if not settings.DEV_MODE:
        raise HTTPException(404, "Not found")
    ref = new_ref()

    users_data = [
        ("patient",   "patient",   ROLE_IDENTITY_MAP["PATIENT"]),
        ("pharmacist", "pharmacist", ROLE_IDENTITY_MAP["PHARMACIST"]),
        ("doctor",    "doctor",    ROLE_IDENTITY_MAP["DOCTOR"]),
        ("driver",    "driver",    ROLE_IDENTITY_MAP["DRIVER"]),
        ("admin",     "admin",     ROLE_IDENTITY_MAP["ADMIN"]),
    ]

    created = []
    for username, role, identity_id in users_data:
        existing = await db.execute(
            select(User).where(User.username == username)
        )
        if existing.scalar_one_or_none():
            created.append({"username": username, "status": "already_exists"})
            continue
        db.add(User(
            username=username,
            role=role,
            identity_id=identity_id,
            hashed_password=hash_password("demo"),
            is_active=True,
        ))
        created.append({"username": username, "status": "created"})

    await db.commit()
    logger.info("Users seeded", ref=ref, count=len(created))
    return APIResponse(status="ok", message="Utilisateurs de démo créés", data={"users": created}, ref=ref)


class SetupFoundersBody(BaseModel):
    ayoub_password: str = "youpipo19"
    eya_password: str = "israbestie4life"


@router.post("/setup-founders")
@limiter.limit("1/minute")
async def dev_setup_founders(request: Request, body: SetupFoundersBody = Body(...), db: AsyncSession = Depends(get_db)):
    secret = request.headers.get("X-Setup-Key")
    if secret != "PHARMAGO_SETUP_2026":
        raise HTTPException(403, "Forbidden")
    ref = new_ref()

    founders = [
        {"username": "ayoub", "email": "ayoubhamdi1746@gmail.com", "password": body.ayoub_password, "role": "super_admin"},
        {"username": "eya",   "email": "eyarzeigui218@gmail.com",   "password": body.eya_password,  "role": "super_admin"},
    ]

    results = []
    for f in founders:
        identity_id = hashlib.sha256(f"{f['username']}:{f['email']}".encode()).hexdigest()
        existing = await db.execute(select(User).where(User.username == f["username"]))
        user = existing.scalar_one_or_none()
        if user:
            user.role = f["role"]
            user.email = f["email"]
            user.identity_id = identity_id
            user.hashed_password = _hash(f["password"])
            user.is_active = True
            results.append({"username": f["username"], "status": "updated"})
        else:
            db.add(User(
                id=str(uuid.uuid4()),
                username=f["username"],
                email=f["email"],
                role=f["role"],
                identity_id=identity_id,
                hashed_password=_hash(f["password"]),
                is_active=True,
            ))
            results.append({"username": f["username"], "status": "created"})

    demo = await db.execute(select(User).where(User.username == "admin"))
    demo_user = demo.scalar_one_or_none()
    if demo_user:
        demo_user.is_active = False
        results.append({"username": "admin", "status": "deactivated"})
    else:
        results.append({"username": "admin", "status": "not_found"})

    try:
        await db.commit()
        logger.info("Founders setup complete", ref=ref)
        return APIResponse(status="ok", message="DELETE /dev/setup-founders after use", data={"results": results}, ref=ref)
    except Exception as e:
        await db.rollback()
        logger.error("Founders setup failed", ref=ref, error=str(e), error_type=type(e).__name__)
        raise HTTPException(500, f"Database error: {type(e).__name__}: {e}")
