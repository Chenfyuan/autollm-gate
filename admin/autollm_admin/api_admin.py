"""管理后台 API：管理员登录（多账号）、租户、模型价格、平台上游 Key、计费设置、告警、监控、概览。Cookie 会话。"""
from __future__ import annotations
import json, os, re
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from autollm_gate.metrics import summarize
from autollm_gate.providers import PROVIDER_CLASSES
from . import reports, security as sec
from .alerts import DEFAULTS as ALERT_DEFAULTS, alert_settings
from .api_console import key_out, mark_paid, tenant_brief, topup_out
from .billing import hash_key, new_api_key, usd
from .db import MICRO, AdminUser, AlertEvent, ApiKey, Setting, Tenant, TenantUser, Topup, UpstreamKey, Usage, iso, now

SETTINGS_CHANNEL = "autollm:settings"


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class AdminIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(default="", max_length=200)
    password: str = Field(max_length=200)


class AdminPatch(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    markup_pct: float | None = Field(default=None, ge=0, le=1000)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    markup_pct: float | None = Field(default=None, ge=0, le=1000)
    rpm_limit: int | None = Field(default=None, ge=1, le=100000)
    active: bool | None = None


class KeyIn(BaseModel):
    name: str = Field(default="", max_length=100)


class UpstreamIn(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=500)


class TopupIn(BaseModel):
    amount_usd: float = Field(gt=0, le=100000)
    note: str = Field(default="", max_length=500)


class SettingsIn(BaseModel):
    platform_markup_pct: float | None = Field(default=None, ge=0, le=1000)
    byok_fee_per_request_usd: float | None = Field(default=None, ge=0)
    byok_fee_per_1k_tokens_usd: float | None = Field(default=None, ge=0)
    alert_enabled: bool | None = None
    alert_webhook_url: str | None = Field(default=None, max_length=500)
    alert_webhook_format: str | None = Field(default=None, pattern="^(generic|feishu|wecom|dingtalk|slack)$")
    alert_error_rate_pct: float | None = Field(default=None, gt=0, le=100)
    alert_min_requests: int | None = Field(default=None, ge=1)
    alert_low_balance_usd: float | None = Field(default=None, ge=0)
    alert_quota_pct: float | None = Field(default=None, gt=0, le=100)
    alert_cooldown_minutes: float | None = Field(default=None, ge=1)


class ModelPatch(BaseModel):
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)
    enabled: bool | None = None


def mask(hint: str) -> str:
    return "••••••••" + (hint or "").lstrip("…")


async def ensure_bootstrap_admin(Session):
    """首次启动：用 ADMIN_BOOTSTRAP_EMAIL / ADMIN_BOOTSTRAP_PASSWORD 创建第一个管理员（已有管理员则忽略）。"""
    email, pw = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower(), os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "")
    if not email or not pw:
        return
    async with Session() as s:
        if await s.scalar(select(func.count()).select_from(AdminUser)):
            return
        s.add(AdminUser(email=email, name="超级管理员", password_hash=sec.hash_password(pw)))
        try:
            await s.commit()
        except Exception:  # 多实例并发启动时另一实例已创建
            await s.rollback()


def build_admin(Session, hooks, state, alerter, channels: dict) -> APIRouter:
    r = APIRouter(prefix="/api/admin")
    gw_ref: dict = {}

    async def current(request: Request) -> AdminUser:
        c = sec.read(request, sec.ADMIN_COOKIE, "admin")
        async with Session() as s:
            a = await s.get(AdminUser, c["sub"])
        if not a or not a.active or a.session_version != c.get("sv"):
            raise HTTPException(401, "登录已失效，请重新登录")
        return a

    A = Depends(current)

    async def get_tenant(s, tid) -> Tenant:
        t = await s.get(Tenant, tid)
        if not t:
            raise HTTPException(404, "租户不存在")
        return t

    async def broadcast(kind: str):
        await state.publish(SETTINGS_CHANNEL, kind)

    # ---------------- 认证 ----------------
    @r.post("/auth/login")
    async def login(b: LoginIn, request: Request, response: Response):
        email = b.email.strip().lower()
        ip = sec.client_ip(request)
        await sec.rate_limit(state, f"alogin:ip:{ip}", int(os.getenv("LOGIN_RATE_PER_MIN", "20")), 60, "admin_login")
        await sec.rate_limit(state, f"alogin:email:{email}", 10, 900, "admin_login")
        async with Session() as s:
            a = await s.scalar(select(AdminUser).where(AdminUser.email == email))
            if not sec.verify_password(a.password_hash if a else None, b.password) or not a.active:
                raise HTTPException(401, "邮箱或密码错误")
            a.last_login_at = now()
            await s.commit()
        sec.issue(response, sec.ADMIN_COOKIE, a.id, "admin", a.session_version, int(os.getenv("ADMIN_SESSION_HOURS", "12")))
        return {"ok": True}

    @r.post("/auth/logout")
    async def logout(response: Response):
        sec.clear(response, sec.ADMIN_COOKIE)
        return {"ok": True}

    @r.get("/me")
    async def me(a: AdminUser = A):
        return {"id": a.id, "email": a.email, "name": a.name}

    # ---------------- 管理员账号 ----------------
    def admin_out(a: AdminUser):
        return {"id": a.id, "email": a.email, "name": a.name, "active": a.active, "created_at": iso(a.created_at), "last_login_at": iso(a.last_login_at)}

    @r.get("/admins")
    async def admins(a: AdminUser = A):
        async with Session() as s:
            return [admin_out(x) for x in await s.scalars(select(AdminUser).order_by(AdminUser.created_at))]

    @r.post("/admins")
    async def create_admin(b: AdminIn, a: AdminUser = A):
        sec.validate_password(b.password)
        async with Session() as s:
            email = b.email.strip().lower()
            if await s.scalar(select(AdminUser).where(AdminUser.email == email)):
                raise HTTPException(409, "该邮箱已是管理员")
            x = AdminUser(email=email, name=b.name, password_hash=sec.hash_password(b.password))
            s.add(x)
            await s.commit()
            return admin_out(x)

    @r.patch("/admins/{aid}")
    async def patch_admin(aid: str, b: AdminPatch, a: AdminUser = A):
        async with Session() as s:
            x = await s.get(AdminUser, aid)
            if not x:
                raise HTTPException(404, "管理员不存在")
            if b.active is False and x.id == a.id:
                raise HTTPException(400, "不能停用自己")
            if b.active is not None:
                x.active = b.active
                x.session_version += 1
            if b.name is not None:
                x.name = b.name
            if b.password:
                sec.validate_password(b.password)
                x.password_hash = sec.hash_password(b.password)
                x.session_version += 1  # 改密后其它会话全部失效
            await s.commit()
            return admin_out(x)

    # ---------------- 概览 ----------------
    @r.get("/overview")
    async def overview(days: int = 30, a: AdminUser = A):
        days = max(1, min(days, 90))
        since = reports.range_start(days)
        async with Session() as s:
            tot = await reports.totals(s, since)
            month = await reports.totals(s, reports.month_start())
            today = await reports.totals(s, reports.range_start(1))
            series = await reports.daily(s, days)
            models = await reports.by_model(s, since)
            top = (await s.execute(select(Tenant.id, Tenant.name, func.count(Usage.id), func.sum(Usage.charge_micro))
                                   .join(Usage, Usage.tenant_id == Tenant.id).where(Usage.created_at >= since)
                                   .group_by(Tenant.id, Tenant.name).order_by(func.sum(Usage.charge_micro).desc()).limit(5))).all()
            n_tenants = await s.scalar(select(func.count()).select_from(Tenant))
            balance = await s.scalar(select(func.coalesce(func.sum(Tenant.balance_micro), 0)))
            src = (await s.execute(select(Usage.key_source, func.count(), func.sum(Usage.charge_micro), func.sum(Usage.cost_micro))
                                   .where(Usage.created_at >= since).group_by(Usage.key_source))).all()
        return {"totals": tot, "month": month, "today": today, "series": series, "models": models[:8], "tenants": n_tenants,
                "balance_usd": usd(balance), "top_tenants": [{"id": i, "name": n, "requests": c, "charge_usd": usd(m)} for i, n, c, m in top],
                "by_source": [{"key_source": k, "requests": c, "charge_usd": usd(ch), "cost_usd": usd(co)} for k, c, ch, co in src]}

    # ---------------- 租户 ----------------
    @r.get("/tenants")
    async def tenants(q: str = "", a: AdminUser = A):
        ms = reports.month_start()
        async with Session() as s:
            stmt = select(Tenant).order_by(Tenant.created_at.desc())
            if q:
                stmt = stmt.where(Tenant.name.ilike(f"%{q}%"))
            ts = (await s.scalars(stmt)).all()
            spend = {i: (c, m, tok) for i, c, m, tok in (await s.execute(
                select(Usage.tenant_id, func.count(), func.sum(Usage.charge_micro), func.sum(Usage.prompt_tokens + Usage.completion_tokens))
                .where(Usage.created_at >= ms).group_by(Usage.tenant_id))).all()}
            emails = {}
            for tid, em in (await s.execute(select(TenantUser.tenant_id, TenantUser.email).order_by(TenantUser.created_at))).all():
                emails.setdefault(tid, em)
            keys = dict((await s.execute(select(ApiKey.tenant_id, func.count()).where(ApiKey.active.is_(True)).group_by(ApiKey.tenant_id))).all())
        ts = sorted(ts, key=lambda t: -(spend.get(t.id, (0, 0, 0))[1] or 0))
        return [{**tenant_brief(t), "email": emails.get(t.id), "markup_pct": t.markup_pct, "rpm_limit": t.rpm_limit,
                 "month_requests": spend.get(t.id, (0, 0, 0))[0], "month_charge_usd": usd(spend.get(t.id, (0, 0, 0))[1]),
                 "month_tokens": int(spend.get(t.id, (0, 0, 0))[2] or 0), "active_keys": keys.get(t.id, 0)} for t in ts]

    @r.post("/tenants")
    async def create_tenant(b: TenantIn, a: AdminUser = A):
        async with Session() as s:
            t = Tenant(name=b.name, monthly_token_limit=b.monthly_token_limit, markup_pct=b.markup_pct)
            s.add(t)
            await s.commit()
            return tenant_brief(t)

    @r.get("/tenants/{tid}")
    async def tenant_detail(tid: str, a: AdminUser = A):
        async with Session() as s:
            t = await get_tenant(s, tid)
            users = (await s.scalars(select(TenantUser).where(TenantUser.tenant_id == tid))).all()
            keys = (await s.scalars(select(ApiKey).where(ApiKey.tenant_id == tid).order_by(ApiKey.created_at.desc()))).all()
            tps = (await s.scalars(select(Topup).where(Topup.tenant_id == tid).order_by(Topup.created_at.desc()).limit(50))).all()
            byok = (await s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id == tid, UpstreamKey.active.is_(True)))).all()
            recent = (await s.scalars(select(Usage).where(Usage.tenant_id == tid).order_by(Usage.id.desc()).limit(20))).all()
            knames = {k.id: k.name or "未命名" for k in keys}
            return {**tenant_brief(t), "markup_pct": t.markup_pct, "rpm_limit": t.rpm_limit,
                    "users": [{"email": u.email, "name": u.name, "last_login_at": iso(u.last_login_at)} for u in users],
                    "keys": [key_out(k) for k in keys], "topups": [topup_out(x) for x in tps],
                    "byok": [{"id": u.id, "provider": u.provider, "masked": mask(u.hint)} for u in byok],
                    "series": await reports.daily(s, 30, tid), "models": await reports.by_model(s, reports.range_start(30), tid),
                    "month": await reports.totals(s, reports.month_start(), tid),
                    "recent": [{"id": x.id, "created_at": iso(x.created_at), "model": x.model, "key_name": knames.get(x.api_key_id, "—"),
                                "prompt_tokens": x.prompt_tokens, "completion_tokens": x.completion_tokens, "charge_usd": usd(x.charge_micro),
                                "key_source": x.key_source, "latency_ms": x.latency_ms} for x in recent]}

    @r.patch("/tenants/{tid}")
    async def patch_tenant(tid: str, b: TenantPatch, a: AdminUser = A):
        async with Session() as s:
            t = await get_tenant(s, tid)
            for k, v in b.model_dump(exclude_unset=True).items():
                setattr(t, k, v)
            await s.commit()
            return tenant_brief(t)

    @r.post("/tenants/{tid}/keys")
    async def create_key(tid: str, b: KeyIn, a: AdminUser = A):
        async with Session() as s:
            await get_tenant(s, tid)
            raw = new_api_key()
            k = ApiKey(tenant_id=tid, name=b.name or "后台创建", prefix=raw[:10], key_hash=hash_key(raw))
            s.add(k)
            await s.commit()
            return {**key_out(k), "api_key": raw}

    @r.delete("/keys/{kid}")
    async def revoke_key(kid: str, a: AdminUser = A):
        async with Session() as s:
            k = await s.get(ApiKey, kid)
            if not k:
                raise HTTPException(404, "Key 不存在")
            k.active, k.revoked_at = False, now()
            await s.commit()
            return {"ok": True}

    @r.post("/tenants/{tid}/topups")
    async def admin_topup(tid: str, b: TopupIn, a: AdminUser = A):
        """后台手工入账（线下转账等），立即生效。"""
        async with Session() as s:
            await get_tenant(s, tid)
            tp = Topup(tenant_id=tid, amount_micro=round(b.amount_usd * MICRO), channel="manual", note=b.note or f"管理员 {a.email} 手工入账")
            s.add(tp)
            await s.flush()
            await mark_paid(s, tp, None)
            await s.commit()
            await s.refresh(tp)
            return topup_out(tp)

    # ---------------- 上游 Key ----------------
    async def _set_upstream(s, tenant_id, b: UpstreamIn):
        if b.provider not in PROVIDER_CLASSES:
            raise HTTPException(400, f"provider 必须是 {sorted(PROVIDER_CLASSES)}")
        cond = UpstreamKey.tenant_id.is_(None) if tenant_id is None else UpstreamKey.tenant_id == tenant_id
        for old in await s.scalars(select(UpstreamKey).where(cond, UpstreamKey.provider == b.provider, UpstreamKey.active.is_(True))):
            old.active = False
        key = b.api_key.strip()
        u = UpstreamKey(tenant_id=tenant_id, provider=b.provider, enc_key=hooks.vault.encrypt(key), hint="…" + key[-4:])
        s.add(u)
        await s.commit()
        hooks.invalidate_upstreams()
        await broadcast("upstreams")
        return {"id": u.id, "provider": u.provider, "masked": mask(u.hint), "scope": "platform" if tenant_id is None else "byok"}

    @r.get("/upstreams")
    async def list_upstreams(a: AdminUser = A):
        async with Session() as s:
            rows = (await s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id.is_(None), UpstreamKey.active.is_(True)))).all()
        have = {u.provider: u for u in rows}
        return [{"provider": p, "configured": p in have, "id": have[p].id if p in have else None,
                 "masked": mask(have[p].hint) if p in have else None, "updated_at": iso(have[p].created_at) if p in have else None}
                for p in PROVIDER_CLASSES]

    @r.put("/upstreams")
    async def set_upstream(b: UpstreamIn, a: AdminUser = A):
        async with Session() as s:
            return await _set_upstream(s, None, b)

    @r.put("/tenants/{tid}/upstream")
    async def set_tenant_upstream(tid: str, b: UpstreamIn, a: AdminUser = A):
        async with Session() as s:
            await get_tenant(s, tid)
            return await _set_upstream(s, tid, b)

    @r.delete("/upstreams/{uid_}")
    async def delete_upstream(uid_: str, a: AdminUser = A):
        async with Session() as s:
            u = await s.get(UpstreamKey, uid_)
            if not u:
                raise HTTPException(404, "不存在")
            u.active = False
            await s.commit()
        hooks.invalidate_upstreams()
        await broadcast("upstreams")
        return {"ok": True}

    # ---------------- 模型与价格 ----------------
    @r.get("/models")
    async def models(a: AdminUser = A):
        p = hooks.pricing
        out = []
        for name, m in p.cfg["models"].items():
            base = p.base_models.get(name, m)
            out.append({"model": name, "provider": m["provider"], "context": m.get("context"), "enabled": m.get("enabled", True) is not False,
                        "price_in": m["price_in"], "price_out": m["price_out"], "default_price_in": base["price_in"],
                        "default_price_out": base["price_out"], "quality": m.get("quality"), "speed": m.get("speed")})
        return {"markup_pct": p.markup_pct, "models": out}

    @r.patch("/models/{name}")
    async def patch_model(name: str, b: ModelPatch, a: AdminUser = A):
        p = hooks.pricing
        if name not in p.base_models:
            raise HTTPException(404, "模型不存在")
        async with Session() as s:
            row = await s.get(Setting, "model_overrides")
            ov = json.loads(row.value) if row else {}
            ov.setdefault(name, {}).update(b.model_dump(exclude_none=True))
            if row:
                row.value = json.dumps(ov)
            else:
                s.add(Setting(key="model_overrides", value=json.dumps(ov)))
            await s.commit()
        await p.load(Session)
        await broadcast("settings")
        return {"ok": True}

    # ---------------- 计费 & 告警设置 ----------------
    def settings_out():
        p = hooks.pricing
        al = alert_settings(p.raw)
        return {**p.as_dict(), "alert_enabled": al["alert_enabled"] == "1", "alert_webhook_url": al["alert_webhook_url"],
                "alert_webhook_format": al["alert_webhook_format"], "alert_error_rate_pct": float(al["alert_error_rate_pct"]),
                "alert_min_requests": int(float(al["alert_min_requests"])), "alert_low_balance_usd": float(al["alert_low_balance_usd"]),
                "alert_quota_pct": float(al["alert_quota_pct"]), "alert_cooldown_minutes": float(al["alert_cooldown_minutes"]),
                "mock_payment": "mock" in channels, "env": os.getenv("ENV", "development")}

    @r.get("/settings")
    async def get_settings(a: AdminUser = A):
        return settings_out()

    @r.put("/settings")
    async def put_settings(b: SettingsIn, a: AdminUser = A):
        url = b.alert_webhook_url
        if url and not re.match(r"^https?://", url.strip()):
            raise HTTPException(422, "Webhook 地址必须以 http:// 或 https:// 开头")
        async with Session() as s:
            for k, v in b.model_dump(exclude_none=True).items():
                v = ("1" if v else "0") if isinstance(v, bool) else str(v).strip()
                row = await s.get(Setting, k)
                if row:
                    row.value = v
                else:
                    s.add(Setting(key=k, value=v))
            await s.commit()
        await hooks.pricing.load(Session)
        await broadcast("settings")
        return settings_out()

    # ---------------- 监控 & 告警 ----------------
    @r.get("/monitoring")
    async def monitoring(minutes: int = 15, a: AdminUser = A):
        minutes = max(5, min(minutes, 120))
        stats = await summarize(state, list(PROVIDER_CLASSES), minutes)
        gw = gw_ref.get("gw")
        br = gw.breakers.snapshot() if gw else {}
        async with Session() as s:
            evs = (await s.scalars(select(AlertEvent).order_by(AlertEvent.id.desc()).limit(30))).all()
            configured = set(await s.scalars(select(UpstreamKey.provider).where(UpstreamKey.tenant_id.is_(None), UpstreamKey.active.is_(True))))
        return {"minutes": minutes, "state_backend": state.kind,
                "providers": [{"provider": p, "configured": p in configured, "breaker": br.get(p, {"state": "closed", "failures": 0}), **st}
                              for p, st in stats.items()],
                "alerts": [{"id": e.id, "kind": e.kind, "severity": e.severity, "title": e.title, "message": e.message,
                            "delivered": e.delivered, "delivery_error": e.delivery_error, "created_at": iso(e.created_at)} for e in evs]}

    @r.post("/alerts/test")
    async def test_alert(a: AdminUser = A):
        ev = await alerter.fire("test", "test", "测试告警", f"这是一条由管理员 {a.email} 触发的测试告警，收到说明 Webhook 配置正确。", "info", force=True)
        return {"delivered": ev.delivered, "error": ev.delivery_error}

    @r.post("/alerts/evaluate")
    async def eval_alerts(a: AdminUser = A):
        return {"fired": [e.title for e in await alerter.evaluate()]}

    @r.get("/topups")
    async def all_topups(a: AdminUser = A):
        async with Session() as s:
            rows = (await s.execute(select(Topup, Tenant.name).join(Tenant, Tenant.id == Topup.tenant_id)
                                    .order_by(Topup.created_at.desc()).limit(200))).all()
        return [{**topup_out(t), "tenant_id": t.tenant_id, "tenant_name": n} for t, n in rows]

    r.gw_ref = gw_ref  # type: ignore[attr-defined]
    return r


def build_webhooks(Session, channels: dict) -> APIRouter:
    r = APIRouter()

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
        async with Session() as s:
            tp = await s.get(Topup, tid)
            if not tp or tp.channel != channel:
                raise HTTPException(404, "订单不存在")
            if paid:
                await mark_paid(s, tp, ext)
            elif tp.status == "pending":
                tp.status = "failed"
            await s.commit()
            await s.refresh(tp)
            return topup_out(tp)
    return r
