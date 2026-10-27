from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DB_PATH = Path(__file__).parent / "demo.db"
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
