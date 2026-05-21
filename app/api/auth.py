import hashlib
import structlog
import traceback
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.logging.cfg import new_ref
from app.schemas.common import APIResponse, LoginRequest, TokenResponse, RefreshRequest, PharmacyRegisterRequest, PatientRegisterRequest, DriverRegisterRequest
from app.models.user import User
from app.models.billing import PharmacySubscription, SubscriptionPlan, PLAN_PRICES, PLAN_LIMITS
from app.models.pharmacy_profile import PharmacyProfile
from app.services.auth_service import (
    verify_password, create_access_token, create_refresh_token, decode_token, hash_password,
    revoke_token,
)
from app.limiter import limiter


class RegisterPharmacyRequest(BaseModel):
    pharmacy_name: str
    responsible_name: str
    phone: str
    city: str
    plan: str


router = APIRouter()
logger = structlog.get_logger()


@router.post("/login")
@limiter.limit("5/15minute")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ref = new_ref()
    username = body.username
    password = body.password
    try:
        result = await db.execute(
            select(User).where(User.username == body.username)
        )
        user = result.scalar_one_or_none()
        if not user:
            logger.warning("auth.login_failed", reason="user_not_found", username=body.username, ref=ref)
            raise HTTPException(401, "Nom d'utilisateur ou mot de passe incorrect")

        if not user.hashed_password:
            logger.error("auth.login_no_hash", username=body.username, ref=ref)
            raise HTTPException(500, "Compte mal configuré, contactez l'administrateur")

        try:
            password_ok = verify_password(body.password, user.hashed_password)
        except Exception as pe:
            logger.error("auth.verify_error", error=str(pe), type=type(pe).__name__, username=body.username, ref=ref)
            raise HTTPException(500, "Erreur interne verification")

        if not password_ok:
            logger.warning("auth.login_failed", reason="bad_password", username=body.username, ref=ref)
            raise HTTPException(401, "Nom d'utilisateur ou mot de passe incorrect")

        user_id = str(getattr(user, 'id', '') or '')
        role_val = getattr(user, 'role', 'unknown') or 'unknown'
        identity_val = getattr(user, 'identity_id', '') or ''

        logger.info("auth.login_steps", username=body.username, ref=ref, step="before_access_token")

        access_token = create_access_token(user_id, role_val, identity_val)
        refresh_token = create_refresh_token(user_id, role_val, identity_val)

        logger.info("auth.login_success", username=body.username, role=role_val, ref=ref)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error("auth.login_crash", traceback=tb, error_type=type(e).__name__, username=body.username, ref=ref)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Erreur interne", "ref": ref},
        )


@router.post("/register-pharmacy")
@limiter.limit("3/minute")
async def register_pharmacy(body: RegisterPharmacyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        plan_enum = SubscriptionPlan(body.plan.upper())
    except ValueError:
        raise HTTPException(400, "Invalid plan. Choose STARTER, PRO, or ENTERPRISE")

    price = PLAN_PRICES[plan_enum]
    limit = PLAN_LIMITS[plan_enum]
    pharmacy_id = str(uuid.uuid4())
    username = f"pharm_{body.pharmacy_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
    password = uuid.uuid4().hex[:12]
    identity_id = hashlib.sha256(f"{username}:{pharmacy_id}".encode()).hexdigest()

    user = User(
        username=username,
        role="pharmacist",
        identity_id=identity_id,
        hashed_password=hash_password(password),
        is_active=True,
        pharmacy_id=pharmacy_id,
        city=body.city,
    )
    db.add(user)

    sub = PharmacySubscription(
        id=uuid.UUID(pharmacy_id),
        pharmacy_name=body.pharmacy_name,
        pharmacy_id=uuid.UUID(pharmacy_id),
        city=body.city,
        responsible_name=body.responsible_name,
        plan=plan_enum,
        price_tnd=price,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
        is_active=True,
        delivery_limit=limit,
    )
    db.add(sub)
    await db.commit()

    logger.info("pharmacy.registered", pharmacy_name=body.pharmacy_name, pharmacy_id=pharmacy_id)
    return APIResponse(status="ok", message="Pharmacy registered. Login credentials will be provided separately.", data={
        "pharmacy_id": pharmacy_id,
        "username": username,
    })


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("5/minute")
async def refresh(body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        logger.warning("auth.refresh_invalid_token")
        raise HTTPException(401, "Invalid or expired refresh token")

    user_id = payload.get("sub")
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "User not found or inactive")

    # Revoke old refresh token (rotation)
    try:
        await revoke_token(body.refresh_token)
    except Exception as e:
        logger.warning("auth.refresh_revoke_failed", error=str(e))

    access_token = create_access_token(user.id, user.role, user.identity_id)
    refresh_token = create_refresh_token(user.id, user.role, user.identity_id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/register/pharmacy")
@limiter.limit("3/minute")
async def register_pharmacy(body: PharmacyRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        ref = new_ref()
        # Validate email uniqueness
        result = await db.execute(select(User).where(User.email == body.email))
        if result.scalar_one_or_none():
            from app.exceptions.handlers import ConflictException
            raise ConflictException("Email already registered", ref)

        # Validate plan
        try:
            plan_enum = SubscriptionPlan(body.plan.upper())
        except ValueError:
            raise HTTPException(400, "Invalid plan. Choose STARTER, PRO, or ENTERPRISE")

        # Hash password
        hashed_password = hash_password(body.password)
        
        # Generate IDs
        pharmacy_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        identity_id = hashlib.sha256(f"{body.email}:{pharmacy_id}".encode()).hexdigest()
        
        # Create user
        user = User(
            id=user_id,
            username=body.email.split('@')[0][:20],
            email=body.email,
            hashed_password=hashed_password,
            role="pharmacist",
            identity_id=identity_id,
            is_active=False,
            pharmacy_id=pharmacy_id,
            city=body.city,
            pharmacist_license_hash=identity_id,
        )
        db.add(user)
        
        # Create pharmacy profile
        pharmacy_profile = PharmacyProfile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            pharmacy_name=body.pharmacy_name,
            city=body.city,
            address=body.address,
            phone=body.phone,
        )
        db.add(pharmacy_profile)
        
        # Create subscription
        subscription = PharmacySubscription(
            id=uuid.uuid4(),
            pharmacy_id=uuid.UUID(pharmacy_id),
            pharmacy_name=body.pharmacy_name,
            city=body.city,
            responsible_name=body.owner_name,
            plan=plan_enum,
            price_tnd=PLAN_PRICES[plan_enum],
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
            is_active=True,
            delivery_count_this_month=0,
            delivery_limit=PLAN_LIMITS[plan_enum],
        )
        db.add(subscription)
        
        await db.commit()
        
        logger.info("pharmacy.registered", pharmacy_name=body.pharmacy_name, pharmacy_id=pharmacy_id)
        
        return APIResponse(status="ok", message="Pharmacy registration submitted for verification", data={
            "user_id": user_id,
            "pharmacy_id": pharmacy_id,
            "subscription_id": str(subscription.id),
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("auth.pharmacy_registration_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.post("/register/patient")
@limiter.limit("5/minute")
async def register_patient(body: PatientRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        ref = new_ref()
        # Validate email uniqueness
        result = await db.execute(select(User).where(User.email == body.email))
        if result.scalar_one_or_none():
            from app.exceptions.handlers import ConflictException
            raise ConflictException("Email already registered", ref)

        # Hash password
        hashed_password = hash_password(body.password)
        
        # Generate IDs
        user_id = str(uuid.uuid4())
        identity_id = hashlib.sha256(f"{body.email}:{user_id}".encode()).hexdigest()
        
        # Create user
        user = User(
            id=user_id,
            username=body.email.split('@')[0][:20],
            email=body.email,
            hashed_password=hashed_password,
            role="patient",
            identity_id=identity_id,
            is_active=True,
        )
        db.add(user)
        
        await db.commit()
        
        # Generate access token
        access_token = create_access_token(user.id, user.role, user.identity_id)
        refresh_token = create_refresh_token(user.id, user.role, user.identity_id)
        
        logger.info("patient.registered", email=body.email)
        
        return APIResponse(status="ok", message="Patient registered successfully", data={
            "user_id": user_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("auth.patient_registration_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")


@router.post("/register/driver")
@limiter.limit("5/minute")
async def register_driver(body: DriverRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        ref = new_ref()
        # Validate email uniqueness
        result = await db.execute(select(User).where(User.email == body.email))
        if result.scalar_one_or_none():
            from app.exceptions.handlers import ConflictException
            raise ConflictException("Email already registered", ref)

        # Validate pharmacy exists
        pharmacy_result = await db.execute(select(User).where(User.id == body.pharmacy_id, User.role == "pharmacist"))
        if not pharmacy_result.scalar_one_or_none():
            raise HTTPException(400, "Invalid pharmacy ID")

        # Hash password
        hashed_password = hash_password(body.password)
        
        # Generate IDs
        user_id = str(uuid.uuid4())
        identity_id = hashlib.sha256(f"{body.email}:{user_id}".encode()).hexdigest()
        
        # Create user
        user = User(
            id=user_id,
            username=body.email.split('@')[0][:20],
            email=body.email,
            hashed_password=hashed_password,
            role="driver",
            identity_id=identity_id,
            is_active=False,  # Pending verification by pharmacy
            pharmacy_id=body.pharmacy_id,
        )
        db.add(user)
        
        await db.commit()
        
        logger.info("driver.registered", email=body.email, pharmacy_id=body.pharmacy_id)
        
        return APIResponse(status="ok", message="Driver registration submitted for pharmacy verification", data={
            "user_id": user_id,
        })
    except HTTPException:
        raise
    except Exception as e:
        tb = "".join(traceback.format_exc())
        logger.error("auth.driver_registration_error", traceback=tb, error=str(e))
        raise HTTPException(500, "Internal server error")
