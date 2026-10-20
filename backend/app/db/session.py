import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def init_db(database_url: str) -> None:
    global _engine, _SessionLocal
    logger.info("Initializing database: %s", database_url)
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        from sqlalchemy import event
        @event.listens_for(_engine, "connect")
        def _sqlite_enable_fk(dbapi_conn, _conn_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    from app.db.audit_guard import install as _install_audit_guard
    _install_audit_guard()
    from app.core.rls_context import install_session_rls_hook
    install_session_rls_hook(_SessionLocal)


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _engine


@contextmanager
def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
