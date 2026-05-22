import structlog, re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.demo_request import DemoRequest
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


@router.get("/pharmacies")
@limiter.limit("30/minute")
async def list_pharmacies(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User
    from app.models.pharmacy_profile import PharmacyProfile
    from sqlalchemy import select

    rows = (await db.execute(
        select(User.id, PharmacyProfile.pharmacy_name, PharmacyProfile.city)
        .join(PharmacyProfile, User.id == PharmacyProfile.user_id)
        .where(User.role == "pharmacist", User.is_active == True)
        .order_by(PharmacyProfile.pharmacy_name)
    )).all()

    return APIResponse(status="ok", message="", data={
        "pharmacies": [
            {"id": str(row[0]), "name": row[1] or "Pharmacie", "city": row[2] or ""}
            for row in rows
        ],
    })


class DemoRequestCreate(BaseModel):
    name: str
    pharmacy: str
    city: str = ""
    phone: str = ""
    message: str = ""


@router.post("/demo-request")
@limiter.limit("2/minute")
async def create_demo_request(request: Request, body: DemoRequestCreate, db: AsyncSession = Depends(get_db)):
    ref = new_ref()
    from app.database import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS demo_requests (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                pharmacy VARCHAR(255) NOT NULL,
                city VARCHAR(100),
                phone VARCHAR(50),
                email VARCHAR(255),
                message TEXT,
                is_processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
    demo = DemoRequest(
        name=body.name,
        pharmacy=body.pharmacy,
        city=body.city,
        phone=body.phone,
        message=body.message,
    )
    db.add(demo)
    await db.commit()
    logger.info("demo_request.created", ref=ref, name=body.name, pharmacy=body.pharmacy)
    return APIResponse(status="ok", message="Demande reçue. Nous vous contacterons sous 24h.", data={"id": demo.id}, ref=ref)


@router.get("/demo-requests")
@limiter.limit("30/minute")
async def list_demo_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN)),
):
    total = await db.execute(select(func.count(DemoRequest.id)))
    total = total.scalar()

    rows = (await db.execute(
        select(DemoRequest).order_by(DemoRequest.created_at.desc()).limit(100)
    )).scalars().all()

    return APIResponse(status="ok", message="", data={
        "requests": [
            {
                "id": r.id,
                "name": r.name,
                "pharmacy": r.pharmacy,
                "city": r.city,
                "phone": r.phone,
                "message": r.message,
                "is_processed": r.is_processed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
    }, ref=new_ref())


@router.patch("/demo-requests/{request_id}/process")
@limiter.limit("20/minute")
async def mark_demo_processed(
    request: Request,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.SUPER_ADMIN, Role.ADMIN)),
):
    demo = await db.get(DemoRequest, request_id)
    if not demo:
        from app.exceptions.handlers import NotFoundException
        raise NotFoundException("Demo request not found", new_ref())
    demo.is_processed = True
    await db.commit()
    return APIResponse(status="ok", message="Marked as processed", data={"id": demo.id}, ref=new_ref())


class NewsletterEmail(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
            raise HTTPException(400, "Invalid email format")
        if len(v) > 254:
            raise HTTPException(400, "Email too long")
        return v.lower()


@router.post("/newsletter")
@limiter.limit("3/minute")
async def subscribe_newsletter(request: Request, body: NewsletterEmail, db: AsyncSession = Depends(get_db)):
    ref = new_ref()
    logger.info("newsletter.subscribe", email=body.email, ref=ref)
    return APIResponse(
        status="ok",
        message="Inscrit avec succès",
        data={"email": body.email},
        ref=ref,
    )