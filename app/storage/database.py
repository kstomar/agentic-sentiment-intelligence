"""PostgreSQL-only engine factory and explicit Alembic schema setup."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

from app.core.exceptions import ApplicationError, ErrorCode

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'gmail_incremental_v1'


def create_database_engine(value: SecretStr | str | None) -> Engine:
    try:
        if value is None:
            raise ValueError
        url = make_url(value.get_secret_value() if isinstance(value, SecretStr) else value)
        if url.drivername != 'postgresql+psycopg':
            raise ValueError
        options = url.query.get('options', '') + ' -c statement_timeout=5000 -c lock_timeout=3000'
        return create_engine(url, echo=False, hide_parameters=True, pool_size=4, max_overflow=0,
            pool_timeout=5, pool_pre_ping=True,
            connect_args={'connect_timeout': 5, 'options': options, 'application_name': 'sentiment_batch'})
    except Exception:
        raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE) from None


def upgrade_database(value: SecretStr | str) -> None:
    """Explicit migration helper; application startup never implicitly creates tables."""
    engine = create_database_engine(value)
    config = Config(str(ROOT/'alembic.ini'))
    try:
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
    except Exception:
        raise ApplicationError(ErrorCode.BATCH_UNAVAILABLE) from None
    finally:
        engine.dispose()
