"""v0.3 治理能力：Key 级策略（模型白名单 / IP 白名单 / 过期 / 消费上限）、请求日志检索与导出、审计日志。"""
from __future__ import annotations
import csv, io, ipaddress, json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from .billing import client_ip, split_csv, usd
from .db import MICRO, ApiKey, AuditLog, Usage, iso


class KeyPolicy(BaseModel):
    name: str = Field(default="", max_length=100)
    allowed_models: list[str] | None = None
    ip_allowlist: list[str] | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    expires_at: datetime | None = None
    clear_expiry: bool = False
    spend_limit_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    clear_spend_limit: bool = False
    rpm_limit: int | None = Field(default=None, ge=1, le=100000)

    @field_validator("ip_allowlist")
    @classmethod
    def _ips(cls, v):
        for x in v or []:
            try:
                ipaddress.ip_network(x.strip(), strict=False)
            except ValueError:
                raise ValueError(f"IP/CIDR 格式错误：{x}")
        return [x.strip() for x in v or [] if x.strip()]

    @field_validator("allowed_models")
    @classmethod
    def _models(cls, v):
        out = [x.strip() for x in v or [] if x.strip()]
        if len(out) > 100 or any(len(x) > 100 for x in out):
            raise ValueError("模型白名单过长")
        return out


def apply_policy(k: ApiKey, b: KeyPolicy, *, creating: bool = False):
    if b.name.strip() or creating:
        k.name = b.name.strip() or k.name or "未命名"
    if b.allowed_models is not None:
        k.allowed_models = ",".join(b.allowed_models)
    if b.ip_allowlist is not None:
        k.ip_allowlist = ",".join(b.ip_allowlist)
    if b.clear_expiry:
        k.expires_at = None
    elif b.expires_at:
        k.expires_at = b.expires_at if b.expires_at.tzinfo else b.expires_at.replace(tzinfo=timezone.utc)
    elif b.expires_in_days:
        k.expires_at = datetime.now(timezone.utc) + timedelta(days=b.expires_in_days)
    if b.clear_spend_limit:
        k.spend_limit_micro = None
    elif b.spend_limit_usd is not None:
        k.spend_limit_micro = round(b.spend_limit_usd * MICRO)
    if b.rpm_limit is not None:
        k.rpm_limit = b.rpm_limit


def policy_out(k: ApiKey) -> dict:
    return {"allowed_models": split_csv(k.allowed_models), "ip_allowlist": split_csv(k.ip_allowlist),
            "expires_at": iso(k.expires_at), "spend_limit_usd": usd(k.spend_limit_micro) if k.spend_limit_micro is not None else None,
            "spent_usd": usd(k.spent_micro or 0)}


async def audit(s, request: Request | None, actor_type: str, actor: str, action: str, target: str = "",
                tenant_id: str | None = None, detail: dict | None = None):
    s.add(AuditLog(actor_type=actor_type, actor=actor, tenant_id=tenant_id, action=action, target=target[:200],
                   detail=json.dumps(detail or {}, ensure_ascii=False)[:4000], ip=(client_ip(request) if request else "")[:64]))


def audit_out(a: AuditLog) -> dict:
    return {"id": a.id, "created_at": iso(a.created_at), "actor_type": a.actor_type, "actor": a.actor, "tenant_id": a.tenant_id,
            "action": a.action, "target": a.target, "detail": json.loads(a.detail or "{}"), "ip": a.ip}


def _parse_day(v: str | None, end=False):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"日期格式错误：{v}")
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return d + timedelta(days=1) if end and len(v) <= 10 else d


def log_query(*, tenant_id=None, model=None, provider=None, status=None, api_key_id=None, start=None, end=None):
    q = select(Usage)
    if tenant_id:
        q = q.where(Usage.tenant_id == tenant_id)
    if model:
        q = q.where(Usage.model.contains(model))
    if provider:
        q = q.where(Usage.provider == provider)
    if status:
        q = q.where(Usage.status == status)
    if api_key_id:
        q = q.where(Usage.api_key_id == api_key_id)
    if (s := _parse_day(start)):
        q = q.where(Usage.created_at >= s)
    if (e := _parse_day(end, end=True)):
        q = q.where(Usage.created_at < e)
    return q


def log_row(x: Usage, key_names: dict | None = None) -> dict:
    return {"id": x.id, "created_at": iso(x.created_at), "tenant_id": x.tenant_id, "api_key_id": x.api_key_id,
            "key_name": (key_names or {}).get(x.api_key_id, ""), "model": x.model, "provider": x.provider,
            "key_source": x.key_source, "strategy": x.strategy, "prompt_tokens": x.prompt_tokens,
            "completion_tokens": x.completion_tokens, "cost_usd": usd(x.cost_micro), "charge_usd": usd(x.charge_micro),
            "latency_ms": x.latency_ms, "status": x.status}


CSV_COLS = ["id", "created_at", "tenant_id", "key_name", "model", "provider", "key_source", "strategy",
            "prompt_tokens", "completion_tokens", "charge_usd", "latency_ms", "status"]


def to_csv(rows: list[dict], cols=CSV_COLS) -> str:
    buf = io.StringIO()
    buf.write("\ufeff")  # Excel 打开中文不乱码
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in r.items()})  # 防 CSV 注入
    return buf.getvalue()
