import structlog, json, asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, Role, role_required, UserContext
from app.schemas.common import APIResponse
from app.models.delivery import Delivery
from app.models.driver_tracking import DriverLocation
from app.logging.cfg import new_ref
from app.limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

ACTIVE_STREAMS: dict[str, asyncio.Queue] = {}


async def event_generator(delivery_id: str, queue: asyncio.Queue):
    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        ACTIVE_STREAMS.pop(delivery_id, None)


@router.get("/tracking/{delivery_id}/stream")
@limiter.limit("30/minute")
async def stream_delivery_tracking(
    delivery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT, Role.PHARMACIST)),
):
    delivery = await db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "Delivery not found")

    if delivery_id not in ACTIVE_STREAMS:
        ACTIVE_STREAMS[delivery_id] = asyncio.Queue()

    queue = ACTIVE_STREAMS[delivery_id]
    return StreamingResponse(
        event_generator(delivery_id, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy: float | None = None
    speed: float | None = None
    bearing: float | None = None


@router.post("/tracking/{delivery_id}/location")
@limiter.limit("60/minute")
async def update_driver_location(
    delivery_id: str,
    body: LocationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.DRIVER)),
):
    location = DriverLocation(
        driver_id=user.id,
        delivery_id=delivery_id,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy=body.accuracy,
        speed=body.speed,
        bearing=body.bearing,
        recorded_at=datetime.now(timezone.utc),
    )
    db.add(location)
    await db.commit()

    if delivery_id in ACTIVE_STREAMS:
        event = {"type": "location", "latitude": body.latitude, "longitude": body.longitude, "timestamp": datetime.now(timezone.utc).isoformat()}
        await ACTIVE_STREAMS[delivery_id].put(event)

    return APIResponse(status="ok", message="Location updated")


@router.get("/tracking/{delivery_id}/history")
@limiter.limit("30/minute")
async def get_delivery_tracking_history(
    delivery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT, Role.PHARMACIST, Role.DRIVER)),
):
    locations = (await db.execute(
        select(DriverLocation)
        .where(DriverLocation.delivery_id == delivery_id)
        .order_by(DriverLocation.recorded_at.desc())
        .limit(100)
    )).scalars().all()

    return APIResponse(status="ok", message="Tracking history", data={
        "locations": [
            {
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "speed": loc.speed,
                "recorded_at": loc.recorded_at.isoformat(),
            }
            for loc in locations
        ],
    })


@router.get("/tracking/{delivery_id}/status")
@limiter.limit("30/minute")
async def get_delivery_status(
    delivery_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(role_required(Role.PATIENT, Role.PHARMACIST, Role.DRIVER)),
):
    delivery = await db.get(Delivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "Delivery not found")

    latest = (await db.execute(
        select(DriverLocation)
        .where(DriverLocation.delivery_id == delivery_id)
        .order_by(DriverLocation.recorded_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    return APIResponse(status="ok", message="Delivery status", data={
        "delivery_id": delivery_id,
        "status": delivery.status,
        "driver_id": delivery.driver_id,
        "estimated_minutes": None,
        "current_location": {
            "latitude": latest.latitude,
            "longitude": latest.longitude,
        } if latest else None,
    })
