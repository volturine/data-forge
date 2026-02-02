from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import JSON, DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings


class Base(DeclarativeBase):
    type_annotation_map = {
        dict: JSON,
        list: JSON,
        datetime: DateTime(timezone=True),
    }


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # Only log SQL queries in debug mode
    connect_args={'check_same_thread': False} if 'sqlite' in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
