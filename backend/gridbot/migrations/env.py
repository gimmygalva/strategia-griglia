from alembic import context
from gridbot.schema import Base
from sqlalchemy import create_engine, pool

config = context.config


def run_migrations_online():
    engine = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
