import asyncio
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("start")


async def check_db():
    from app.database import engine
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        logger.info("DB connection OK")


async def check_users():
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        logger.info("Users found: %d", len(users))
        for u in users:
            logger.info("  - %s (%s)", u.username, u.role)


def start():
    """Verify health and start uvicorn with auto-restart."""
    asyncio.run(check_db())
    asyncio.run(check_users())

    import uvicorn

    logger.info("Starting uvicorn on 127.0.0.1:8001")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.getcwd())
    start()
