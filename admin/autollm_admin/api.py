"""管理 API（ADMIN_TOKEN 保护）+ 租户自助计费 API + 简易后台页面。"""
from __future__ import annotations
import hmac, os
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from autollm_gate.providers import PROVIDER_CLASSES
from .billing import BillingHooks, hash_key, new_api_key, usd
from .db import MICRO, ApiKey, Setting, Tenant, Topup, UpstreamKey, Usage, now


class TenantIn(BaseModel):
    name: str
    monthly_token_limit: int | None = None
    markup_pct: float | None = None


class TenantPatch(BaseModel):
    name: str | None = None
    monthly_token_limit: int | None = None
    markup_pct: float | None = None
    active: bool | None = None


class KeyIn(BaseModel):
    name: str = ""


class UpstreamIn(BaseModel):
    provider: str
    api_key: str = Field(min_length=8)


class SettingsIn(BaseModel):
    platform_markup_pct: float | None = Field(default=None, ge=0, le=1000)
    byok_fee_per_request_usd: float | None = Field(default=None, ge=0)
    byok_fee_per_1k_tokens_usd: float | None = Field(default=None, ge=0)


class TopupIn(BaseModel):
    amount_usd: float = Field(gt=0, le=100000)
    channel: str = "manual"
    note: str = ""


def tenant_out(t: Tenant):
    return {"id": t.id, "name": t.name, "balance_usd": usd(t.balance_micro), "monthly_token_limit": t.monthly_token_limit,
            "markup_pct": t.markup_pct, "active": t.active, "created_at": t.created_at.isoformat()}


def topup_out(t: Topup):
    return {"id": t.id, "tenant_id": t.tenant_id, "amount_usd": usd(t.amount_micro), "channel": t.channel, "status": t.status,
            "external_id": t.external_id, "note": t.note, "created_at": t.created_at.isoformat(),
            "paid_at": t.paid_at.isoformat() if t.paid_at else None}


def mark_paid(s, tp: Topup, external_id: str | None):
    if tp.status == "paid":  # 幂等
        return
    tp.status, tp.paid_at, tp.external_id = "paid", now(), external_id or tp.external_id
    s.get(Tenant, tp.tenant_id).balance_micro += tp.amount_micro


def build_admin(Session, hooks: BillingHooks, channels: dict) -> APIRouter:
    r = APIRouter()
    vault = hooks.vault

    def admin_auth(x_admin_token: str = Header(default="")):
        tok = os.getenv("ADMIN_TOKEN")
        if not tok or not hmac.compare_digest(x_admin_token, tok):
            raise HTTPException(401, "需要有效的 X-Admin-Token")

    A = [Depends(admin_auth)]

    def get_tenant(s, tid):
        t = s.get(Tenant, tid)
        if not t:
            raise HTTPException(404, "租户不存在")
        return t

    @r.get("/admin/api/settings", dependencies=A)
    def get_settings():
        return hooks.pricing.as_dict()

    @r.put("/admin/api/settings", dependencies=A)
    def put_settings(b: SettingsIn):
        with Session() as s:
            for k, v in b.model_dump(exclude_none=True).items():
                row = s.get(Setting, k)
                if row:
                    row.value = str(v)
                else:
                    s.add(Setting(key=k, value=str(v)))
            s.commit()
        return hooks.pricing.load(Session).as_dict()

    @r.post("/admin/api/tenants", dependencies=A)
    def create_tenant(b: TenantIn):
        with Session() as s:
            t = Tenant(name=b.name, monthly_token_limit=b.monthly_token_limit, markup_pct=b.markup_pct)
            s.add(t); s.commit()
            return tenant_out(t)

    @r.get("/admin/api/tenants", dependencies=A)
    def list_tenants():
        with Session() as s:
            return [tenant_out(t) for t in s.scalars(select(Tenant).order_by(Tenant.created_at))]

    @r.patch("/admin/api/tenants/{tid}", dependencies=A)
    def patch_tenant(tid: str, b: TenantPatch):
        with Session() as s:
            t = get_tenant(s, tid)
            for k, v in b.model_dump(exclude_unset=True).items():
                setattr(t, k, v)
            s.commit()
            return tenant_out(t)

    @r.post("/admin/api/tenants/{tid}/keys", dependencies=A)
    def create_key(tid: str, b: KeyIn):
        with Session() as s:
            get_tenant(s, tid)
            raw = new_api_key()
            k = ApiKey(tenant_id=tid, name=b.name, prefix=raw[:10], key_hash=hash_key(raw))
            s.add(k); s.commit()
            return {"id": k.id, "api_key": raw, "note": "明文仅显示这一次"}

    @r.get("/admin/api/tenants/{tid}/keys", dependencies=A)
    def list_keys(tid: str):
        with Session() as s:
            return [{"id": k.id, "name": k.name, "prefix": k.prefix, "active": k.active, "created_at": k.created_at.isoformat(),
                     "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}
                    for k in s.scalars(select(ApiKey).where(ApiKey.tenant_id == tid))]

    @r.delete("/admin/api/keys/{kid}", dependencies=A)
    def revoke_key(kid: str):
        with Session() as s:
            k = s.get(ApiKey, kid)
            if not k:
                raise HTTPException(404, "Key 不存在")
            k.active = False; s.commit()
            return {"ok": True}

    def _set_upstream(s, tenant_id, b: UpstreamIn):
        if b.provider not in PROVIDER_CLASSES:
            raise HTTPException(400, f"provider 必须是 {sorted(PROVIDER_CLASSES)}")
        for old in s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id.is_(None) if tenant_id is None else UpstreamKey.tenant_id == tenant_id,
                                                       UpstreamKey.provider == b.provider, UpstreamKey.active.is_(True))):
            old.active = False
        u = UpstreamKey(tenant_id=tenant_id, provider=b.provider, enc_key=vault.encrypt(b.api_key), hint="…" + b.api_key[-4:])
        s.add(u); s.commit()
        return {"id": u.id, "provider": u.provider, "hint": u.hint, "scope": "platform" if tenant_id is None else "byok"}

    def _list_upstream(s, tenant_id):
        q = select(UpstreamKey).where(UpstreamKey.active.is_(True),
                                      UpstreamKey.tenant_id.is_(None) if tenant_id is None else UpstreamKey.tenant_id == tenant_id)
        return [{"id": u.id, "provider": u.provider, "hint": u.hint} for u in s.scalars(q)]

    @r.put("/admin/api/platform/upstream", dependencies=A)
    def set_platform_upstream(b: UpstreamIn):
        with Session() as s:
            return _set_upstream(s, None, b)

    @r.get("/admin/api/platform/upstream", dependencies=A)
    def list_platform_upstream():
        with Session() as s:
            return _list_upstream(s, None)

    @r.put("/admin/api/tenants/{tid}/upstream", dependencies=A)
    def set_tenant_upstream(tid: str, b: UpstreamIn):
        with Session() as s:
            get_tenant(s, tid)
            return _set_upstream(s, tid, b)

    @r.delete("/admin/api/upstream/{uid_}", dependencies=A)
    def delete_upstream(uid_: str):
        with Session() as s:
            u = s.get(UpstreamKey, uid_)
            if not u:
                raise HTTPException(404, "不存在")
            u.active = False; s.commit()
            return {"ok": True}

    @r.post("/admin/api/tenants/{tid}/topups", dependencies=A)
    def admin_topup(tid: str, b: TopupIn):
        """后台手工入账（线下转账等），立即生效。"""
        with Session() as s:
            get_tenant(s, tid)
            tp = Topup(tenant_id=tid, amount_micro=round(b.amount_usd * MICRO), channel="manual", note=b.note)
            s.add(tp); s.flush(); mark_paid(s, tp, None); s.commit()
            return topup_out(tp)

    @r.get("/admin/api/topups", dependencies=A)
    def list_topups(tenant_id: str | None = None):
        with Session() as s:
            q = select(Topup).order_by(Topup.created_at.desc())
            if tenant_id:
                q = q.where(Topup.tenant_id == tenant_id)
            return [topup_out(t) for t in s.scalars(q.limit(500))]

    @r.get("/admin/api/usage", dependencies=A)
    def usage_stats(tenant_id: str | None = None):
        with Session() as s:
            q = select(Usage.tenant_id, Usage.model, Usage.key_source, func.count(), func.sum(Usage.prompt_tokens),
                       func.sum(Usage.completion_tokens), func.sum(Usage.cost_micro), func.sum(Usage.charge_micro))
            if tenant_id:
                q = q.where(Usage.tenant_id == tenant_id)
            rows = s.execute(q.group_by(Usage.tenant_id, Usage.model, Usage.key_source)).all()
            return [{"tenant_id": a, "model": b, "key_source": c, "requests": d, "prompt_tokens": e or 0, "completion_tokens": f or 0,
                     "cost_usd": usd(g or 0), "charge_usd": usd(h or 0)} for a, b, c, d, e, f, g, h in rows]

    # ------------- 租户自助（用租户 API Key） -------------
    async def tenant_ctx(request: Request):
        return await hooks.authenticate(request, for_billing=True)

    @r.get("/billing/balance")
    async def my_balance(request: Request):
        ctx = await tenant_ctx(request)
        with Session() as s:
            return tenant_out(s.get(Tenant, ctx.tenant_id))

    @r.get("/billing/usage")
    async def my_usage(request: Request, limit: int = 100):
        ctx = await tenant_ctx(request)
        with Session() as s:
            rows = s.scalars(select(Usage).where(Usage.tenant_id == ctx.tenant_id).order_by(Usage.id.desc()).limit(min(limit, 1000)))
            return [{"model": u.model, "provider": u.provider, "key_source": u.key_source, "prompt_tokens": u.prompt_tokens,
                     "completion_tokens": u.completion_tokens, "charge_usd": usd(u.charge_micro), "created_at": u.created_at.isoformat()}
                    for u in rows]

    @r.get("/billing/topups")
    async def my_topups(request: Request):
        ctx = await tenant_ctx(request)
        with Session() as s:
            return [topup_out(t) for t in s.scalars(select(Topup).where(Topup.tenant_id == ctx.tenant_id).order_by(Topup.created_at.desc()))]

    @r.post("/billing/topups")
    async def create_topup(request: Request, b: TopupIn):
        ctx = await tenant_ctx(request)
        ch = channels.get(b.channel)
        if not ch or b.channel == "manual":
            raise HTTPException(400, f"不支持的支付渠道，可选 {sorted(channels)}")
        with Session() as s:
            tp = Topup(tenant_id=ctx.tenant_id, amount_micro=round(b.amount_usd * MICRO), channel=b.channel)
            s.add(tp); s.commit()
            try:
                checkout = ch.create_checkout(tp.id, tp.amount_micro)
            except NotImplementedError as e:
                tp.status = "failed"; tp.note = str(e); s.commit()
                raise HTTPException(501, str(e))
            return {**topup_out(tp), "checkout": checkout}

    @r.post("/billing/webhook/{channel}")
    async def webhook(channel: str, request: Request):
        ch = channels.get(channel)
        if not ch:
            raise HTTPException(404, "未知渠道")
        payload = await request.json()
        try:
            tid, ext, paid = ch.verify_webhook(dict(request.headers), payload)
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        with Session() as s:
            tp = s.get(Topup, tid)
            if not tp or tp.channel != channel:
                raise HTTPException(404, "订单不存在")
            if paid:
                mark_paid(s, tp, ext)
            elif tp.status == "pending":
                tp.status = "failed"
            s.commit()
            return topup_out(tp)

    @r.get("/admin", response_class=HTMLResponse)
    def dashboard():
        return (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")

    return r
