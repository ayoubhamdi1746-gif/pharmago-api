import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.review import Review
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


class CreateReviewRequest(BaseModel):
    target_type: str = Field(pattern=r"^(pharmacy|driver)$")
    target_id: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


@router.post("")
@limiter.limit("10/minute")
async def create_review(
    body: CreateReviewRequest, request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    ref = new_ref()
    existing = await db.execute(
        select(Review).where(
            Review.author_id == user.id,
            Review.target_type == body.target_type,
            Review.target_id == body.target_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "You have already reviewed this resource")

    review = Review(
        author_id=user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(review)
    await db.commit()
    return APIResponse(status="ok", message="Review created", data={"id": review.id}, ref=ref)


@router.get("")
@limiter.limit("30/minute")
async def list_reviews(
    request: Request,
    db: AsyncSession = Depends(get_db),
    target_type: str | None = None,
    target_id: str | None = None,
):
    ref = new_ref()
    query = select(Review).where(Review.is_visible == True)
    if target_type:
        query = query.where(Review.target_type == target_type)
    if target_id:
        query = query.where(Review.target_id == target_id)
    query = query.order_by(Review.created_at.desc())

    rows = (await db.execute(query)).scalars().all()
    avg_query = select(func.avg(Review.rating)).where(Review.is_visible == True)
    if target_type:
        avg_query = avg_query.where(Review.target_type == target_type)
    if target_id:
        avg_query = avg_query.where(Review.target_id == target_id)
    avg = await db.execute(avg_query)

    return APIResponse(status="ok", message="Reviews", data={
        "reviews": [
            {
                "id": str(r.id),
                "author_id": r.author_id,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "rating": r.rating,
                "comment": r.comment,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "average_rating": float(avg.scalar() or 0),
        "total": len(rows),
    }, ref=ref)


@router.get("/stats/{target_type}/{target_id}")
@limiter.limit("30/minute")
async def get_review_stats(
    request: Request,
    target_type: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
):
    ref = new_ref()
    stats = await db.execute(
        select(
            func.count(Review.id),
            func.avg(Review.rating),
            func.min(Review.rating),
            func.max(Review.rating),
        ).where(
            Review.target_type == target_type,
            Review.target_id == target_id,
            Review.is_visible == True,
        )
    )
    count, avg, mn, mx = stats.one()
    distribution = {}
    for r in range(1, 6):
        cnt = await db.execute(
            select(func.count(Review.id)).where(
                Review.target_type == target_type,
                Review.target_id == target_id,
                Review.rating == r,
                Review.is_visible == True,
            )
        )
        distribution[r] = cnt.scalar() or 0

    return APIResponse(status="ok", message="Review stats", data={
        "total_reviews": count,
        "average_rating": float(avg) if avg else 0,
        "min_rating": int(mn) if mn else 0,
        "max_rating": int(mx) if mx else 0,
        "distribution": distribution,
    }, ref=ref)
