"""租户自助控制台 API：注册/登录、API Key、用量、账单明细、余额充值、模型价格。Cookie 会话。"""
from __future__ import annotations
import os, re
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import reports, security as sec
from .billing import hash_key, new_api_key, usd
from .db import MICRO, ApiKey, Tenant, TenantUser, Topup, Usage, iso, now

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    company: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class KeyIn(BaseModel):
    name: str = Field(default="", max_length=100)


class TopupIn(BaseModel):
    amount_usd: float = Field(gt=0, le=100000)
    channel: str


def tenant_brief(t: Tenant):
    return {"id": t.id, "name": t.name, "balance_usd": usd(t.balance_micro), "reserved_usd": usd(t.reserved_micro),
            "monthly_token_limit": t.monthly_token_limit, "active": t.active, "created_at": iso(t.created_at)}


def topup_out(t: Topup):
    return {"id": t.id, "amount_usd": usd(t.amount_micro), "channel": t.channel, "status": t.status, "external_id": t.external_id,
            "note": t.note, "created_at": iso(t.created_at), "paid_at": iso(t.paid_at)}


def key_out(k: ApiKey):
    return {"id": k.id, "name": k.name or "未命名", "prefix": k.prefix, "active": k.active, "rpm_limit": k.rpm_limit,
            "created_at": iso(k.created_at), "last_used_at": iso(k.last_used_at), "revoked_at": iso(k.revoked_at)}


async def mark_paid(s, tp: Topup, external_id: str | None):
    """幂等入账：条件 UPDATE 保证同一订单只入账一次。"""
    from sqlalchemy import update
    res = await s.execute(update(Topup).where(Topup.id == tp.id, Topup.status != "paid")
                          .values(status="paid", paid_at=now(), external_id=external_id or tp.external_id))
    if res.rowcount == 1:
        await s.execute(update(Tenant).where(Tenant.id == tp.tenant_id).values(balance_micro=Tenant.balance_micro + tp.amount_micro))


def build_console(Session, hooks, state, channels: dict) -> APIRouter:
    r = APIRouter(prefix="/api")
    mock_enabled = "mock" in channels

    async def current(request: Request) -> TenantUser:
        c = sec.read(request, sec.TENANT_COOKIE, "tenant")
        async with Session() as s:
            u = await s.get(TenantUser, c["sub"])
        if not u or u.session_version != c.get("sv"):
            raise HTTPException(401, "登录已失效，请重新登录")
        return u

    U = Depends(current)

    @r.post("/auth/signup")
    async def signup(b: SignupIn, request: Request, response: Response):
        if os.getenv("ALLOW_SIGNUP", "1") != "1":
            raise HTTPException(403, "当前未开放自助注册，请联系管理员")
        ip = sec.client_ip(request)
        await sec.rate_limit(state, f"signup:{ip}", int(os.getenv("SIGNUP_RATE_PER_HOUR", "5")), 3600, "signup")
        email = b.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(422, "邮箱格式不正确")
        sec.validate_password(b.password)
        async with Session() as s:
            if await s.scalar(select(TenantUser).where(TenantUser.email == email)):
                raise HTTPException(409, "该邮箱已注册，请直接登录")
            credit = round(float(os.getenv("SIGNUP_CREDIT_USD", "0")) * MICRO)
            t = Tenant(name=b.company.strip(), balance_micro=credit)
            s.add(t)
            await s.flush()
            if credit:
                s.add(Topup(tenant_id=t.id, amount_micro=credit, channel="manual", status="paid", note="新用户赠送额度", paid_at=now()))
            u = TenantUser(tenant_id=t.id, email=email, name=b.name.strip(), password_hash=sec.hash_password(b.password), last_login_at=now())
            s.add(u)
            await s.commit()
        sec.issue(response, sec.TENANT_COOKIE, u.id, "tenant", u.session_version, int(os.getenv("TENANT_SESSION_HOURS", "168")))
        return {"ok": True}

    @r.post("/auth/login")
    async def login(b: LoginIn, request: Request, response: Response):
        email = b.email.strip().lower()
        ip = sec.client_ip(request)
        await sec.rate_limit(state, f"login:ip:{ip}", int(os.getenv("LOGIN_RATE_PER_MIN", "20")), 60, "login")
        await sec.rate_limit(state, f"login:email:{email}", 10, 900, "login")
        async with Session() as s:
            u = await s.scalar(select(TenantUser).where(TenantUser.email == email))
            if not sec.verify_password(u.password_hash if u else None, b.password):
                raise HTTPException(401, "邮箱或密码错误")
            u.last_login_at = now()
            await s.commit()
        sec.issue(response, sec.TENANT_COOKIE, u.id, "tenant", u.session_version, int(os.getenv("TENANT_SESSION_HOURS", "168")))
        return {"ok": True}

    @r.post("/auth/logout")
    async def logout(response: Response):
        sec.clear(response, sec.TENANT_COOKIE)
        return {"ok": True}

    @r.get("/me")
    async def me(u: TenantUser = U):
        async with Session() as s:
            t = await s.get(Tenant, u.tenant_id)
        return {"user": {"id": u.id, "email": u.email, "name": u.name}, "tenant": tenant_brief(t), "mock_payment": mock_enabled}

    @r.get("/console/overview")
    async def overview(u: TenantUser = U):
        async with Session() as s:
            t = await s.get(Tenant, u.tenant_id)
            month = await reports.totals(s, reports.month_start(), t.id)
            today = await reports.totals(s, reports.range_start(1), t.id)
            series = await reports.daily(s, 30, t.id)
            models = await reports.by_model(s, reports.range_start(30), t.id)
            keys = await s.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == t.id, ApiKey.active.is_(True)))
        return {"tenant": tenant_brief(t), "month": month, "today": today, "series": series, "models": models[:6], "active_keys": keys}

    @r.get("/console/usage")
    async def usage(days: int = 30, u: TenantUser = U):
        days = max(1, min(days, 90))
        async with Session() as s:
            return {"daily": await reports.daily(s, days, u.tenant_id), "by_model_daily": await reports.daily(s, days, u.tenant_id, by_model=True),
                    "models": await reports.by_model(s, reports.range_start(days), u.tenant_id),
                    "totals": await reports.totals(s, reports.range_start(days), u.tenant_id)}

    @r.get("/console/billing")
    async def billing(page: int = 1, size: int = 20, model: str | None = None, u: TenantUser = U):
        size = max(1, min(size, 100))
        async with Session() as s:
            q = select(Usage).where(Usage.tenant_id == u.tenant_id)
            if model:
                q = q.where(Usage.model == model)
            total = await s.scalar(select(func.count()).select_from(q.subquery()))
            rows = (await s.scalars(q.order_by(Usage.id.desc()).offset((page - 1) * size).limit(size))).all()
            names = dict((await s.execute(select(ApiKey.id, ApiKey.name).where(ApiKey.tenant_id == u.tenant_id))).all())
        return {"total": total, "page": page, "size": size, "items": [
            {"id": x.id, "created_at": iso(x.created_at), "model": x.model, "provider": x.provider, "key_source": x.key_source,
             "key_name": names.get(x.api_key_id) or ("未命名" if x.api_key_id in names else "—"), "prompt_tokens": x.prompt_tokens, "completion_tokens": x.completion_tokens,
             "charge_usd": usd(x.charge_micro), "latency_ms": x.latency_ms, "status": x.status} for x in rows]}

    @r.get("/console/keys")
    async def keys(u: TenantUser = U):
        async with Session() as s:
            rows = (await s.scalars(select(ApiKey).where(ApiKey.tenant_id == u.tenant_id).order_by(ApiKey.created_at.desc()))).all()
        return [key_out(k) for k in rows]

    @r.post("/console/keys")
    async def create_key(b: KeyIn, u: TenantUser = U):
        async with Session() as s:
            n = await s.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == u.tenant_id, ApiKey.active.is_(True)))
            if n >= int(os.getenv("MAX_KEYS_PER_TENANT", "20")):
                raise HTTPException(400, "有效 Key 数量已达上限，请先吊销不用的 Key")
            raw = new_api_key()
            k = ApiKey(tenant_id=u.tenant_id, name=b.name.strip() or "未命名", prefix=raw[:10], key_hash=hash_key(raw))
            s.add(k)
            await s.commit()
        return {**key_out(k), "api_key": raw}

    @r.delete("/console/keys/{kid}")
    async def revoke_key(kid: str, u: TenantUser = U):
        async with Session() as s:
            k = await s.get(ApiKey, kid)
            if not k or k.tenant_id != u.tenant_id:
                raise HTTPException(404, "Key 不存在")
            k.active, k.revoked_at = False, now()
            await s.commit()
        return {"ok": True}

    @r.get("/console/topups")
    async def topups(u: TenantUser = U):
        async with Session() as s:
            rows = (await s.scalars(select(Topup).where(Topup.tenant_id == u.tenant_id).order_by(Topup.created_at.desc()).limit(200))).all()
        return {"items": [topup_out(t) for t in rows],
                "channels": [{"id": k, "name": getattr(v, "label", k), "available": k == "mock" or getattr(v, "available", False)} for k, v in channels.items()]}

    @r.post("/console/topups")
    async def create_topup(b: TopupIn, u: TenantUser = U):
        ch = channels.get(b.channel)
        if not ch:
            raise HTTPException(400, "不支持的支付渠道")
        async with Session() as s:
            tp = Topup(tenant_id=u.tenant_id, amount_micro=round(b.amount_usd * MICRO), channel=b.channel)
            s.add(tp)
            await s.commit()
            try:
                checkout = ch.create_checkout(tp.id, tp.amount_micro)
            except NotImplementedError as e:
                tp.status, tp.note = "failed", str(e)
                await s.commit()
                raise HTTPException(501, str(e))
        return {**topup_out(tp), "checkout": checkout}

    @r.post("/console/topups/{tid}/mock-pay")
    async def mock_pay(tid: str, u: TenantUser = U):
        """仅非生产环境：模拟支付成功。生产环境 mock 渠道不会注册，此接口返回 404。"""
        if not mock_enabled:
            raise HTTPException(404, "未启用模拟支付")
        async with Session() as s:
            tp = await s.get(Topup, tid)
            if not tp or tp.tenant_id != u.tenant_id or tp.channel != "mock":
                raise HTTPException(404, "订单不存在")
            await mark_paid(s, tp, "mock-" + tp.id)
            await s.commit()
            await s.refresh(tp)
        return topup_out(tp)

    @r.get("/models")
    async def models():
        """公开价格表（含平台加价后的售价，单位：美元 / 百万 token）。"""
        p = hooks.pricing
        out = []
        for name, m in p.cfg["models"].items():
            if m.get("enabled") is False:
                continue
            mult = 1 if m["provider"] == "selfhosted" else 1 + p.markup_pct / 100
            out.append({"model": name, "provider": m["provider"], "context": m.get("context"),
                        "price_in": round(m["price_in"] * mult, 4), "price_out": round(m["price_out"] * mult, 4),
                        "quality": m.get("quality"), "speed": m.get("speed")})
        return {"markup_pct": p.markup_pct, "models": out}

    return r
