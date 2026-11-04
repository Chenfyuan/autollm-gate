"""Alembic 环境（异步引擎）。DATABASE_URL 取自环境变量。"""
import asyncio, os
from logging.config import fileConfig
from alembic import context
from autollm_admin.db import Base, async_url, make_engine

config = context.config
if config.config_file_name and os.path.exists(config.config_file_name):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = config.attributes.get("target_metadata", Base.metadata)


def do_run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async():
    conn = config.attributes.get("connection")
    if conn is not None:
        do_run(conn)
        return
    engine = make_engine(config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL"))
    async with engine.connect() as c:
        await c.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=async_url(os.getenv("DATABASE_URL", "")), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async()) if config.attributes.get("connection") is None else do_run(config.attributes["connection"])
