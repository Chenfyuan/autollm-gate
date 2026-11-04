"""报表聚合：按天（报表时区）/ 按模型 / 按租户汇总用量与收入。"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, literal_column, select

from .db import Usage
from .billing import usd

REPORT_TZ = os.getenv("REPORT_TZ", "Asia/Shanghai")


def tz():
    return ZoneInfo(REPORT_TZ)


def day_expr(dialect: str):
    if dialect == "postgresql":
        return func.to_char(func.timezone(REPORT_TZ, Usage.created_at), "YYYY-MM-DD")
    off = datetime.now(tz()).utcoffset() or timedelta(0)
    hours = int(off.total_seconds() // 3600)
    return func.strftime("%Y-%m-%d", Usage.created_at, f"{hours:+d} hours")


def range_start(days: int) -> datetime:
    local_today = datetime.now(tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (local_today - timedelta(days=days - 1)).astimezone(timezone.utc)


def month_start() -> datetime:
    return datetime.now(tz()).replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def day_labels(days: int) -> list[str]:
    today = datetime.now(tz()).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


async def daily(s, days: int, tenant_id: str | None = None, by_model: bool = False):
    d = day_expr(s.bind.dialect.name).label("d")
    cols = [d, func.count(), func.sum(Usage.prompt_tokens + Usage.completion_tokens), func.sum(Usage.charge_micro), func.sum(Usage.cost_micro)]
    if by_model:
        cols.append(Usage.model)
    q = select(*cols).where(Usage.created_at >= range_start(days))
    if tenant_id:
        q = q.where(Usage.tenant_id == tenant_id)
    q = q.group_by(d, Usage.model) if by_model else q.group_by(d)
    rows = (await s.execute(q)).all()
    labels = day_labels(days)
    if not by_model:
        m = {r[0]: r for r in rows}
        return [{"date": x, "requests": int(m[x][1]) if x in m else 0, "tokens": int(m[x][2] or 0) if x in m else 0,
                 "charge_usd": usd(m[x][3]) if x in m else 0.0, "cost_usd": usd(m[x][4]) if x in m else 0.0} for x in labels]
    models = sorted({r[5] for r in rows})
    out = [{"date": x, **{mm: 0.0 for mm in models}} for x in labels]
    idx = {x: i for i, x in enumerate(labels)}
    for r in rows:
        if r[0] in idx:
            out[idx[r[0]]][r[5]] = usd(r[3])
    return {"models": models, "series": out}


async def by_model(s, since: datetime, tenant_id: str | None = None):
    q = select(Usage.model, func.count(), func.sum(Usage.prompt_tokens), func.sum(Usage.completion_tokens),
               func.sum(Usage.charge_micro), func.sum(Usage.cost_micro), func.avg(Usage.latency_ms)).where(Usage.created_at >= since)
    if tenant_id:
        q = q.where(Usage.tenant_id == tenant_id)
    rows = (await s.execute(q.group_by(Usage.model).order_by(func.sum(Usage.charge_micro).desc()))).all()
    return [{"model": a, "requests": b, "prompt_tokens": int(c or 0), "completion_tokens": int(d or 0),
             "charge_usd": usd(e), "cost_usd": usd(f), "avg_latency_ms": int(g or 0)} for a, b, c, d, e, f, g in rows]


async def totals(s, since: datetime, tenant_id: str | None = None):
    q = select(func.count(), func.coalesce(func.sum(Usage.prompt_tokens + Usage.completion_tokens), 0),
               func.coalesce(func.sum(Usage.charge_micro), 0), func.coalesce(func.sum(Usage.cost_micro), 0)).where(Usage.created_at >= since)
    if tenant_id:
        q = q.where(Usage.tenant_id == tenant_id)
    n, tok, ch, co = (await s.execute(q)).one()
    return {"requests": int(n), "tokens": int(tok), "charge_usd": usd(ch), "cost_usd": usd(co)}
