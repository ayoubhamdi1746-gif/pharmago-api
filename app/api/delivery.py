import uuid, hashlib, structlog
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.delivery import Delivery
from app.models.prescription import Prescription
from app.models.user import User
from app.services.auth_service import hash_password
import random
import string

router = APIRouter()
logger = structlog.get_logger()


def generate_otp() -> str:
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


@router.post("/assign/{prescription_id}")
async def assign_delivery(
    prescription_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    try:
        body = await request.json()
        driver_id = body.get("driver_id")
        delivery_address = body.get("delivery_address")
        
        if not driver_id:
            raise HTTPException(400, "driver_id is required")
        if not delivery_address:
            raise HTTPException(400, "delivery_address is required")
        
        # Validate prescription exists and is verified
        prescription_result = await db.execute(
            select(Prescription).where(Prescription.id == str(prescription_id))
        )
        prescription = prescription_result.scalar_one_or_none()
        if not prescription:
            raise HTTPException(404, "Prescription not found")
        
        # Validate prescription is verified or high_risk (ready for delivery)
        if prescription.status not in ["verified", "high_risk"]:
            raise HTTPException(400, "Prescription is not ready for delivery")
        
        # Validate driver exists and is active
        driver_result = await db.execute(
            select(User).where(
                and_(
                    User.id == driver_id,
                    User.role == "driver",
                    User.is_active == True
                )
            )
        )
        driver = driver_result.scalar_one_or_none()
        if not driver:
            raise HTTPException(404, "Driver not found or not active")
        
        # Validate pharmacy owns this prescription
        if prescription.pharmacy_id != user.id:
            raise HTTPException(403, "Not authorized to assign delivery for this prescription")
        
        # Check if delivery already exists for this prescription
        existing_delivery = await db.execute(
            select(Delivery).where(Delivery.prescription_id == str(prescription_id))
        )
        if existing_delivery.scalar_one_or_none():
            raise HTTPException(409, "Delivery already assigned for this prescription")
        
        # Generate OTP
        otp_code = generate_otp()
        otp_expires_at = datetime.utcnow() + timedelta(hours=2)
        
        # Create delivery
        delivery = Delivery(
            id=str(uuid.uuid4()),
            prescription_id=str(prescription_id),
            driver_id=driver_id,
            pharmacy_id=user.id,
            patient_id=prescription.patient_id,
            status="assigned",
            otp_code=otp_code,
            otp_expires_at=otp_expires_at,
            delivery_address=delivery_address,
        )
        db.add(delivery)
        
        await db.commit()
        await db.refresh(delivery)
        
        logger.info("delivery.assigned", delivery_id=delivery.id, prescription_id=str(prescription_id), driver_id=driver_id)
        
        return {
            "status": "ok",
            "message": "Delivery assigned successfully",
            "data": {
                "delivery_id": delivery.id,
                "otp_code": otp_code,  # In production, send via SMS
                "otp_expires_at": otp_expires_at.isoformat(),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("delivery.assign_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.patch("/{delivery_id}/pickup")
async def pickup_delivery(
    delivery_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    try:
        # Get delivery
        delivery_result = await db.execute(
            select(Delivery).where(Delivery.id == str(delivery_id))
        )
        delivery = delivery_result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(404, "Delivery not found")
        
        # Validate driver owns this delivery
        if delivery.driver_id != user.id:
            raise HTTPException(403, "Not authorized to pickup this delivery")
        
        # Validate status
        if delivery.status != "assigned":
            raise HTTPException(400, f"Cannot pickup delivery with status: {delivery.status}")
        
        # Update delivery
        delivery.status = "picked_up"
        delivery.pickup_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info("delivery.picked_up", delivery_id=delivery.id, driver_id=user.id)
        
        return {
            "status": "ok",
            "message": "Delivery picked up successfully",
            "data": {
                "delivery_id": delivery.id,
                "status": delivery.status,
                "pickup_at": delivery.pickup_at.isoformat() if delivery.pickup_at else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("delivery.pickup_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.patch("/{delivery_id}/deliver")
async def deliver_prescription(
    delivery_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    try:
        body = await request.json()
        otp_code = body.get("otp_code")
        
        if not otp_code:
            raise HTTPException(400, "otp_code is required")
        
        # Get delivery
        delivery_result = await db.execute(
            select(Delivery).where(Delivery.id == str(delivery_id))
        )
        delivery = delivery_result.scalar_one_or_none()
        if not delivery:
            raise HTTPException(404, "Delivery not found")
        
        # Validate driver owns this delivery
        if delivery.driver_id != user.id:
            raise HTTPException(403, "Not authorized to deliver this delivery")
        
        # Validate status
        if delivery.status != "picked_up":
            raise HTTPException(400, f"Cannot deliver delivery with status: {delivery.status}")
        
        # Validate OTP
        if not delivery.otp_code or delivery.otp_code != otp_code:
            raise HTTPException(400, "Invalid or expired OTP")
        
        # Check OTP expiration
        if delivery.otp_expires_at and delivery.otp_expires_at < datetime.utcnow():
            raise HTTPException(400, "OTP has expired")
        
        # Update delivery
        delivery.status = "delivered"
        delivery.delivered_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info("delivery.delivered", delivery_id=delivery.id, driver_id=user.id)
        
        return {
            "status": "ok",
            "message": "Delivery completed successfully",
            "data": {
                "delivery_id": delivery.id,
                "status": delivery.status,
                "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("delivery.deliver_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/my")
async def get_driver_deliveries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
    status: str = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        driver_id = user.id
        
        # Build query
        query = select(Delivery).where(Delivery.driver_id == driver_id)
        if status:
            query = query.where(Delivery.status == status)
        
        # Get total count
        total_query = select(func.count(Delivery.id)).where(Delivery.driver_id == driver_id)
        if status:
            total_query = total_query.where(Delivery.status == status)
        total_result = await db.execute(total_query)
        total = total_result.scalar()
        
        # Get paginated results
        offset = (page - 1) * limit
        deliveries_query = query.order_by(Delivery.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(deliveries_query)
        deliveries = result.scalars().all()
        
        delivery_list = []
        for delivery in deliveries:
            delivery_list.append({
                "id": str(delivery.id),
                "prescription_id": delivery.prescription_id,
                "pharmacy_id": delivery.pharmacy_id,
                "patient_id": delivery.patient_id,
                "status": delivery.status,
                "delivery_address": delivery.delivery_address,
                "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
                "updated_at": delivery.updated_at.isoformat() if delivery.updated_at else None,
                "pickup_at": delivery.pickup_at.isoformat() if delivery.pickup_at else None,
                "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
            })
        
        return {
            "status": "ok",
            "message": "Driver deliveries retrieved",
            "data": {
                "deliveries": delivery_list,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": (total + limit - 1) // limit if limit > 0 else 0,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("delivery.my_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/active")
async def get_active_deliveries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        pharmacy_id = user.id
        
        # Get total count
        total_query = select(func.count(Delivery.id)).where(
            and_(
                Delivery.pharmacy_id == pharmacy_id,
                or_(
                    Delivery.status == "assigned",
                    Delivery.status == "picked_up",
                    Delivery.status == "in_transit"
                )
            )
        )
        total_result = await db.execute(total_query)
        total = total_result.scalar()
        
        # Get paginated results
        offset = (page - 1) * limit
        deliveries_query = (
            select(Delivery, User.username.label("patient_name"))
            .join(User, Delivery.patient_id == User.id)
            .where(
                and_(
                    Delivery.pharmacy_id == pharmacy_id,
                    or_(
                        Delivery.status == "assigned",
                        Delivery.status == "picked_up",
                        Delivery.status == "in_transit"
                    )
                )
            )
            .order_by(Delivery.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        
        result = await db.execute(deliveries_query)
        rows = result.all()
        
        deliveries = []
        for delivery, patient_name in rows:
            deliveries.append({
                "id": str(delivery.id),
                "prescription_id": delivery.prescription_id,
                "patient_name": patient_name,
                "status": delivery.status,
                "delivery_address": delivery.delivery_address,
                "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
            })
        
        return {
            "status": "ok",
            "message": "Active deliveries retrieved",
            "data": {
                "deliveries": deliveries,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": (total + limit - 1) // limit if limit > 0 else 0,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("delivery.active_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")