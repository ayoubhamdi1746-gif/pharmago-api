import asyncio
import uvicorn
from app.database import get_engine, get_session_maker
from app.main import app


async def init():
    engine = get_engine()
    from app.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(init())
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
