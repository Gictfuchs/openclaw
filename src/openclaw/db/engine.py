"""SQLAlchemy async engine setup."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(db_path: str) -> None:
    """Initialize the database engine and create tables."""
    global _engine, _session_factory

    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        # WAL mode for better concurrent reads
        connect_args={"check_same_thread": False},
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    # Enable WAL mode and create tables
    from openclaw.memory.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode=WAL"))


def get_session() -> AsyncSession:
    """Get a new async session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory()


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
