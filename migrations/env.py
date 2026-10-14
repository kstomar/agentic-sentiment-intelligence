"""Migration URL comes from private configuration, never the committed INI file."""
import logging

from alembic import context

from app.core.config import Settings
from app.storage.batch_models import Base
from app.storage.feedback_models import FeedbackEventRow  # Register ingestion metadata.
from app.storage.gmail_message_models import GmailMessageRow  # Register message metadata.
from app.storage.database import create_database_engine

config = context.config
for name in ['sqlalchemy', 'alembic', 'psycopg']:
    logging.getLogger(name).setLevel(logging.CRITICAL)


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


try:
    supplied = config.attributes.get('connection')
    if supplied is not None:
        run(supplied)
    else:
        engine = create_database_engine(Settings().database_url)
        try:
            with engine.connect() as connection:
                run(connection)
        finally:
            engine.dispose()
except Exception:
    raise SystemExit('DATABASE_MIGRATION_FAILED: Check private PostgreSQL configuration and connectivity.') from None
