"""MySQL session access."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mockfastapi.config import Settings


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session connected using the current application settings."""
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
