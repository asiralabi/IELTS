from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")

connect_args: dict = {"check_same_thread": False} if _is_sqlite else {}

# A pool is wrong in front of a pooler. Managed Postgres is reached through a
# TRANSACTION-mode pooler (Supabase's Supavisor on :6543), which hands a
# different backend connection to every transaction -- so a client-side pool
# holding connections open across invocations buys nothing and, on a platform
# that freezes the process between requests, hands back sockets the pooler has
# already reclaimed. NullPool opens per checkout and closes on release, which
# is what a serverless function wants. SQLite keeps its own default: it is a
# local file, there is no pooler, and the container path depends on it.
engine_kwargs: dict = {"connect_args": connect_args}
if not _is_sqlite:
    engine_kwargs["poolclass"] = NullPool
    # A frozen instance can be resumed onto a connection the server has since
    # dropped; without this the first query after a thaw raises instead of
    # reconnecting.
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(settings.database_url, **engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    settings.ensure_data_dirs()
    from app import models  # noqa: F401  # register models with Base.metadata

    Base.metadata.create_all(engine)
