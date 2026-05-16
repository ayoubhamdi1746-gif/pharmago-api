import uuid, structlog
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
import json

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
        
        return {
            "status": "ok",
            "message": "Notifications retrieved",
            "data": {
                "notifications": notification_list,
                "pagination": {
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.get_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.patch("/{notification_id}/read")
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
                    Notification.id == str(notification_id),
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
        
        return {
            "status": "ok",
            "message": "Notification marked as read",
            "data": {
                "id": str(notification.id),
                "is_read": True,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.read_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/count/unread")
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
        
        return {
            "status": "ok",
            "message": "Unread notification count retrieved",
            "data": {
                "unread": count,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("notification.count_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")