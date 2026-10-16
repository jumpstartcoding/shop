"""Database engine and session handling.

On Lambda, NullPool opens a connection per request and closes it afterwards, so frozen
containers never hold idle connections. Either Neon endpoint works: the direct one (simplest;
a handful of Lambda containers is far below Neon's connection limit) or the "-pooler" one
(PgBouncer in transaction mode, where server-side prepared statements must be turned off).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"future": True, "connect_args": connect_args(settings.database_url)}
        if settings.on_lambda:
            kwargs["poolclass"] = NullPool
        else:
            kwargs.update(pool_size=5, max_overflow=5, pool_pre_ping=True)
        _engine = create_engine(settings.database_url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def connect_args(url: str) -> dict:
    # Neon's compute may be waking from scale-to-zero; give it a few seconds.
    args: dict = {"connect_timeout": 10}
    if "-pooler." in url:
        args["prepare_threshold"] = None
    return args


def reset_engine() -> None:
    """Used by tests to point the app at a different database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
