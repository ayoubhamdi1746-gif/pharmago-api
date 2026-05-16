import uuid, hashlib, structlog
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.prescription import Prescription, PrescriptionVerification, PrescriptionEvent
from app.models.user import User
from app.models.pharmacy_profile import PharmacyProfile
from app.models.pharmacy import LicensedPharmacist
from app.models.delivery import VettedDriver
from app.logging.cfg import new_ref
import json

router = APIRouter()
logger = structlog.get_logger()


@router.post("")
async def create_prescription(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
):
    try:
        body = await request.json()
        pharmacy_id = body.get("pharmacy_id")
        medications = body.get("medications", [])
        
        if not pharmacy_id:
            raise HTTPException(400, "pharmacy_id is required")
        if not medications or not isinstance(medications, list):
            raise HTTPException(400, "medications must be a non-empty list")
        
        # Validate pharmacy exists and is active
        pharmacy_result = await db.execute(
            select(User).where(
                and_(
                    User.id == pharmacy_id,
                    User.role == "pharmacist",
                    User.is_active == True
                )
            )
        )
        pharmacy = pharmacy_result.scalar_one_or_none()
        if not pharmacy:
            raise HTTPException(404, "Pharmacy not found or not active")
        
        # Validate each medication
        for med in medications:
            if not isinstance(med, dict):
                raise HTTPException(400, "Each medication must be an object")
            if not all(k in med for k in ["name", "dosage", "quantity"]):
                raise HTTPException(400, "Each medication must have name, dosage, and quantity")
            if not isinstance(med["dosage"], (int, float)) or med["dosage"] <= 0:
                raise HTTPException(400, "Dosage must be a positive number")
            if not isinstance(med["quantity"], int) or med["quantity"] <= 0:
                raise HTTPException(400, "Quantity must be a positive integer")
        
        # Create prescription
        prescription_id = str(uuid.uuid4())
        prescription = Prescription(
            id=prescription_id,
            patient_id=user.id,
            pharmacy_id=pharmacy_id,
            medications=medications,
            status="pending",
            risk_level="low",
        )
        db.add(prescription)
        
        # Create initial event
        event = PrescriptionEvent(
            id=str(uuid.uuid4()),
            prescription_id=prescription_id,
            event_type="created",
            actor_id=user.id,
            note="Prescription submitted by patient",
        )
        db.add(event)
        
        await db.commit()
        await db.refresh(prescription)
        
        logger.info("prescription.created", prescription_id=prescription_id, patient_id=user.id, pharmacy_id=pharmacy_id)
        
        return {
            "status": "ok",
            "message": "Prescription created successfully",
            "data": {
                "prescription_id": prescription_id,
                "status": prescription.status,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("prescription.create_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/queue")
async def get_pharmacy_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        pharmacy_id = user.id
        
        # Get total count
        total_query = select(func.count(Prescription.id)).where(
            and_(
                Prescription.pharmacy_id == pharmacy_id,
                or_(
                    Prescription.status == "pending",
                    Prescription.status == "high_risk"
                )
            )
        )
        total_result = await db.execute(total_query)
        total = total_result.scalar()
        
        # Get paginated results
        offset = (page - 1) * limit
        prescriptions_query = (
            select(Prescription, User.username.label("patient_name"))
            .join(User, Prescription.patient_id == User.id)
            .where(
                and_(
                    Prescription.pharmacy_id == pharmacy_id,
                    or_(
                        Prescription.status == "pending",
                        Prescription.status == "high_risk"
                    )
                )
            )
            .order_by(Prescription.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        
        result = await db.execute(prescriptions_query)
        rows = result.all()
        
        prescriptions = []
        for prescription, patient_name in rows:
            prescriptions.append({
                "id": str(prescription.id),
                "patient_name": patient_name,
                "medications": prescription.medications,
                "status": prescription.status,
                "risk_level": prescription.risk_level,
                "created_at": prescription.created_at.isoformat() if prescription.created_at else None,
            })
        
        return {
            "status": "ok",
            "message": "Prescription queue retrieved",
            "data": {
                "prescriptions": prescriptions,
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
        logger.error("prescription.queue_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.patch("/{prescription_id}/verify")
async def verify_prescription(
    prescription_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PHARMACIST)),
):
    try:
        body = await request.json()
        status = body.get("status")
        note = body.get("note", "")
        
        if status not in ["verified", "rejected", "high_risk"]:
            raise HTTPException(400, "Invalid status. Must be verified, rejected, or high_risk")
        
        # Get prescription
        prescription_result = await db.execute(
            select(Prescription).where(Prescription.id == str(prescription_id))
        )
        prescription = prescription_result.scalar_one_or_none()
        if not prescription:
            raise HTTPException(404, "Prescription not found")
        
        # Verify pharmacy owns this prescription
        if prescription.pharmacy_id != user.id:
            raise HTTPException(403, "Not authorized to modify this prescription")
        
        # Update prescription
        prescription.status = status
        prescription.risk_level = "high" if status == "high_risk" else prescription.risk_level
        prescription.pharmacist_note = note
        
        # Create verification record
        verification = PrescriptionVerification(
            id=str(uuid.uuid4()),
            prescription_id=str(prescription_id),
            status=status.upper(),
            pharmacist_id=user.id,
            verified_at=datetime.utcnow() if status == "verified" else None,
            dispensed_at=datetime.utcnow() if status == "verified" else None,
        )
        db.add(verification)
        
        # Create event
        event = PrescriptionEvent(
            id=str(uuid.uuid4()),
            prescription_id=str(prescription_id),
            event_type=status,
            actor_id=user.id,
            note=note,
        )
        db.add(event)
        
        await db.commit()
        
        logger.info("prescription.verified", prescription_id=str(prescription_id), status=status, pharmacist_id=user.id)
        
        return {
            "status": "ok",
            "message": f"Prescription marked as {status}",
            "data": {
                "prescription_id": str(prescription_id),
                "status": status,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("prescription.verify_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.get("/my")
async def get_patient_prescriptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT)),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        patient_id = user.id
        
        # Get total count
        total_query = select(func.count(Prescription.id)).where(Prescription.patient_id == patient_id)
        total_result = await db.execute(total_query)
        total = total_result.scalar()
        
        # Get paginated results
        offset = (page - 1) * limit
        prescriptions_query = (
            select(Prescription)
            .where(Prescription.patient_id == patient_id)
            .order_by(Prescription.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        
        result = await db.execute(prescriptions_query)
        prescriptions = result.scalars().all()
        
        prescription_list = []
        for prescription in prescriptions:
            prescription_list.append({
                "id": str(prescription.id),
                "pharmacy_id": prescription.pharmacy_id,
                "medications": prescription.medications,
                "status": prescription.status,
                "risk_level": prescription.risk_level,
                "image_url": prescription.image_url,
                "created_at": prescription.created_at.isoformat() if prescription.created_at else None,
                "updated_at": prescription.updated_at.isoformat() if prescription.updated_at else None,
            })
        
        return {
            "status": "ok",
            "message": "Patient prescriptions retrieved",
            "data": {
                "prescriptions": prescription_list,
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
        logger.error("prescription.my_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")