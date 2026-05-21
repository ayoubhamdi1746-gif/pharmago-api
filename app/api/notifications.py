import uuid, structlog, traceback
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.notification import Notification
from app.models.user import User
from app.models.prescription import Prescription, PrescriptionVerification
from app.models.delivery import Delivery
from app.models.billing import PharmacySubscription
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()


def create_notification(db: AsyncSession, user_id: str, title: str, message: str, notif_type: str):
    """Helper function to create a notification"""
    notification = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        message=message,
        type=notif_type,
        is_read=False,
    )
    db.add(notification)
    return notification


@router.get("")
@limiter.limit("30/minute")
async def get_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        # Build query
        query = select(Notification).where(Notification.user_id == user.id)
        if unread_only:
            query = query.where(Notification.is_read == False)
        
        # Get total count
        count_query = select(func.count(Notification.id)).where(Notification.user_id == user.id)
        if unread_only:
            count_query = count_query.where(Notification.is_read == False)
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Get paginated results
        notifications_query = query.order_by(desc(Notification.created_at)).offset(offset).limit(limit)
        result = await db.execute(notifications_query)
        notifications = result.scalars().all()
        
        notification_list = []
        for notification in notifications:
            notification_list.append({
                "id": str(notification.id),
                "title": notification.title,
                "message": notification.message,
                "type": notification.type,
                "is_read": notification.is_read,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            })
        
        return APIResponse(status="ok", message="Notifications retrieved", data={
            "notifications": notification_list,
            "pagination": {
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.get_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.patch("/{notification_id}/read")
@limiter.limit("30/minute")
async def mark_notification_as_read(
    notification_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    try:
        # Get notification
        notification_result = await db.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    Notification.user_id == user.id
                )
            )
        )
        notification = notification_result.scalar_one_or_none()
        if not notification:
            raise HTTPException(404, "Notification not found")
        
        # Mark as read
        notification.is_read = True
        await db.commit()
        
        return APIResponse(status="ok", message="Notification marked as read", data={
            "id": str(notification.id),
            "is_read": True,
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.read_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/unread")
@limiter.limit("30/minute")
async def get_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(func.count(Notification.id)).where(
                and_(
                    Notification.user_id == user.id,
                    Notification.is_read == False
                )
            )
        )
        unread_count = result.scalar() or 0
        notifs_result = await db.execute(
            select(Notification).where(
                Notification.user_id == user.id
            ).order_by(desc(Notification.created_at)).limit(20)
        )
        notifications = notifs_result.scalars().all()
        notification_list = [
            {
                "id": str(n.id),
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ]
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.unread_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/count/unread")
@limiter.limit("30/minute")
async def get_unread_notification_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(func.count(Notification.id)).where(
                and_(
                    Notification.user_id == user.id,
                    Notification.is_read == False
                )
            )
        )
        count = result.scalar()
        
        return APIResponse(status="ok", message="Unread notification count retrieved", data={
            "unread": count,
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.count_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")