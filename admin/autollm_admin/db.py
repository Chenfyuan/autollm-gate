"""数据模型（SQLAlchemy 2 异步）。金额统一用「微美元」整数存储；时间全部带时区（UTC）。

表结构变更通过 Alembic 迁移（migrations/），应用启动不再隐式建表（测试 / 本地可设 AUTO_CREATE_TABLES=1）。
"""
from __future__ import annotations
import os, uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MICRO = 1_000_000


def now():
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回的时间不带时区，统一视为 UTC。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: datetime | None) -> str | None:
    dt = aware(dt)
    return dt.isoformat() if dt else None


def uid():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    balance_micro: Mapped[int] = mapped_column(BigInteger, default=0)    # 可用余额
    reserved_micro: Mapped[int] = mapped_column(BigInteger, default=0)   # 进行中请求的预授权冻结额
    monthly_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    markup_pct: Mapped[float | None] = mapped_column(nullable=True)  # 为空则用全局加价
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 租户默认每 Key 每分钟请求数
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class TenantUser(Base):
    __tablename__ = "tenant_users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class UpstreamKey(Base):
    """tenant_id 为空 = 平台统一 Key；否则为租户自带 Key (BYOK)。Fernet 密文存储，接口只返回掩码。"""
    __tablename__ = "upstream_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    enc_key: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(16), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (Index("ix_usage_tenant_created", "tenant_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    api_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(32))
    key_source: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(32))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro: Mapped[int] = mapped_column(BigInteger, default=0)    # 上游成本（估算）
    charge_micro: Mapped[int] = mapped_column(BigInteger, default=0)  # 实际向租户扣费
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class Setting(Base):
    """后台可改的全局配置（覆盖环境变量默认值）。"""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Topup(Base):
    __tablename__ = "topups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    amount_micro: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(32))  # manual / stripe / alipay / wechat / mock
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / paid / failed
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    paid_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))          # upstream_error / low_balance / quota / test
    key: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


def async_url(url: str) -> str:
    """把同步驱动 URL 统一换成异步驱动。"""
    for a, b in (("postgresql+psycopg2://", "postgresql+asyncpg://"), ("postgresql://", "postgresql+asyncpg://"),
                 ("sqlite:///", "sqlite+aiosqlite:///"), ("sqlite://", "sqlite+aiosqlite://")):
        if url.startswith(a) and "+asyncpg" not in url and "+aiosqlite" not in url:
            return b + url[len(a):]
    return url


def make_engine(url: str | None = None):
    url = async_url(url or os.getenv("DATABASE_URL", "sqlite:///./autollm_gate.db"))
    kw: dict = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"timeout": 30}
        if url.endswith("://") or ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            kw["poolclass"] = StaticPool
    else:
        kw.update(pool_pre_ping=True, pool_size=int(os.getenv("DB_POOL_SIZE", "10")), max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")))
    return create_async_engine(url, **kw)


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
