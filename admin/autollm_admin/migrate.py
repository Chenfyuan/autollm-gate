"""数据库迁移入口：python -m autollm_admin.migrate

- 新库：执行全部迁移；
- v0.1 由 create_all 建出来、没有 alembic_version 的旧库：先标记为 0001 基线，再升级到最新；
- 多副本同时启动：PostgreSQL 下用 advisory lock 串行化，只有一个副本真正执行迁移。
"""
from __future__ import annotations
import asyncio, os
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from .db import make_engine

LOCK_ID = 74210931


def _cfg(conn) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    cfg.attributes["connection"] = conn
    return cfg


def _upgrade(conn):
    tables = set(inspect(conn).get_table_names())
    cfg = _cfg(conn)
    if "tenants" in tables and "alembic_version" not in tables:
        command.stamp(cfg, "0001_v01")
    command.upgrade(cfg, "head")


async def migrate(url: str | None = None):
    engine = make_engine(url)
    async with engine.connect() as conn:
        pg = engine.dialect.name == "postgresql"
        if pg:
            await conn.execute(text(f"SELECT pg_advisory_lock({LOCK_ID})"))
        try:
            await conn.run_sync(_upgrade)
            await conn.commit()
        finally:
            if pg:
                await conn.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))
                await conn.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate(os.getenv("DATABASE_URL")))
    print("migrations: up to date")
