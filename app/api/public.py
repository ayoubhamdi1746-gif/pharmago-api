import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.schemas.common import APIResponse
from app.models.demo_request import DemoRequest
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


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
async def list_demo_requests(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, func
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
async def mark_demo_processed(request_id: str, db: AsyncSession = Depends(get_db)):
    demo = await db.get(DemoRequest, request_id)
    if not demo:
        from app.exceptions.handlers import NotFoundException
        raise NotFoundException("Demo request not found", new_ref())
    demo.is_processed = True
    await db.commit()
    return APIResponse(status="ok", message="Marked as processed", data={"id": demo.id}, ref=new_ref())