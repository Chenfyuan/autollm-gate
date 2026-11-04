from __future__ import annotations
import os, uuid
from datetime import datetime, timezone
from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

MICRO = 1_000_000  # 金额统一用「微美元」整数存储，避免浮点误差


def now():
    return datetime.now(timezone.utc)


def uid():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    balance_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    monthly_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    markup_pct: Mapped[float | None] = mapped_column(nullable=True)  # 为空则用全局加价
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UpstreamKey(Base):
    """tenant_id 为空 = 平台统一 Key；否则为租户自带 Key (BYOK)。密文存储。"""
    __tablename__ = "upstream_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    enc_key: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(16), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Usage(Base):
    __tablename__ = "usage"
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
    charge_micro: Mapped[int] = mapped_column(BigInteger, default=0)  # 向租户扣费
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Topup(Base):
    __tablename__ = "topups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    amount_micro: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(32))  # manual / stripe / alipay / wechat ...
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / paid / failed
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_sessionmaker(url: str | None = None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./autollm_gate.db")
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    if url in ("sqlite://", "sqlite:///:memory:"):
        from sqlalchemy.pool import StaticPool
        kw["poolclass"] = StaticPool
    engine = create_engine(url, **kw)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
