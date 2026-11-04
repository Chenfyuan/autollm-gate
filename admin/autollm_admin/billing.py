"""多租户鉴权、限流、上游 Key 解析、额度检查、预授权冻结与结算 —— 实现内核的 GatewayHooks。

计费流程（杜绝透支）：
1. reserve：按候选模型中最贵的一个 ×（估算输入 + max_tokens 或默认输出上限）计算冻结额，
   用条件 UPDATE（balance >= hold）原子地把可用余额转入冻结；并发请求不会把余额扣成负数。
2. record_usage：按实际 token 结算，退回多冻结的部分；若实际超过冻结额，超出部分最多扣到 0，不透支。
3. release：所有上游都失败时全额退回冻结。
"""
from __future__ import annotations
import hashlib, ipaddress, json, logging, os, secrets, time
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from sqlalchemy import case, func, select, text, update

from autollm_gate.hooks import Context, GatewayHooks, bearer
from autollm_gate.metrics import RATE_LIMITED
from .crypto import KeyVault
from .db import MICRO, ApiKey, Setting, Tenant, UpstreamKey, Usage, aware, now

log = logging.getLogger("autollm_admin.billing")


def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


def client_ip(request: Request) -> str:
    """客户端 IP。TRUST_PROXY_HEADERS=1（部署在 nginx 之后）时取 X-Forwarded-For 最左侧地址。"""
    if os.getenv("TRUST_PROXY_HEADERS") == "1":
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        if request.headers.get("x-real-ip"):
            return request.headers["x-real-ip"].strip()
    return request.client.host if request.client else ""


def split_csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def ip_allowed(ip: str, allow: list[str]) -> bool:
    if not allow:
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in allow:
        try:
            if a in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def model_allowed(model: str, allow: list[str]) -> bool:
    """白名单支持精确名与前缀通配（如 gpt-4o*）。"""
    if not allow:
        return True
    return any(model == x or (x.endswith("*") and model.startswith(x[:-1])) for x in allow)


def new_api_key() -> str:
    return "sk-lr-" + secrets.token_urlsafe(32)


def usd(micro: int | None) -> float:
    return round((micro or 0) / MICRO, 6)


class Pricing:
    """三种计费：
    - platform  ：平台统一上游 Key，按上游价 × (1 + 加价%) 扣余额
    - selfhosted：平台自部署开源模型，按 scoring.yaml / 后台设置的售价扣余额
    - byok      ：租户自带 Key，上游费用由租户自付，平台按「每请求 + 每千 token」收服务费（默认 0）
    """
    SETTING_KEYS = {"platform_markup_pct": "markup_pct", "byok_fee_per_request_usd": "byok_req",
                    "byok_fee_per_1k_tokens_usd": "byok_1k"}

    def __init__(self, cfg: dict, markup_pct: float | None = None, byok_fee_per_request: float | None = None,
                 byok_fee_per_1k_tokens: float | None = None):
        self.cfg = cfg
        self.base_models = json.loads(json.dumps(cfg["models"]))  # scoring.yaml 原始定义
        env = lambda k, d: float(os.getenv(k, d))
        self.markup_pct = env("PLATFORM_MARKUP_PCT", "20") if markup_pct is None else markup_pct
        self.byok_req = env("BYOK_FEE_PER_REQUEST_USD", "0") if byok_fee_per_request is None else byok_fee_per_request
        self.byok_1k = env("BYOK_FEE_PER_1K_TOKENS_USD", "0") if byok_fee_per_1k_tokens is None else byok_fee_per_1k_tokens
        self.default_out = int(os.getenv("RESERVE_DEFAULT_OUTPUT_TOKENS", "4096"))
        self.raw: dict[str, str] = {}

    async def load(self, Session):
        """用数据库中的后台配置覆盖环境变量默认值（启动时及收到广播时调用）。"""
        async with Session() as s:
            rows = (await s.scalars(select(Setting))).all()
        self.raw = {r.key: r.value for r in rows}
        for k, attr in self.SETTING_KEYS.items():
            if k in self.raw:
                setattr(self, attr, float(self.raw[k]))
        overrides = json.loads(self.raw.get("model_overrides", "{}") or "{}")
        models = json.loads(json.dumps(self.base_models))
        for name, ov in overrides.items():
            if name in models:
                models[name].update({k: v for k, v in ov.items() if k in ("price_in", "price_out", "enabled")})
        self.cfg["models"].clear()
        self.cfg["models"].update(models)
        return self

    def as_dict(self):
        return {k: getattr(self, a) for k, a in self.SETTING_KEYS.items()}

    @property
    def byok_fee_pct(self):  # >0 表示 BYOK 也需要余额
        return 1 if (self.byok_req or self.byok_1k) else 0

    def model_info(self, model: str) -> dict:
        m = self.cfg["models"].get(model)
        if not m:  # 未知模型按评分表最贵模型保守计价
            m = max(self.cfg["models"].values(), key=lambda v: v["price_out"])
        return m

    def cost_micro(self, model: str, pt: int, ct: int) -> int:
        m = self.model_info(model)
        return round(pt * m["price_in"] + ct * m["price_out"])  # $/1M token * token = 微美元

    def charge_micro(self, cost: int, key_source: str, tenant_markup: float | None, tokens: int = 0) -> int:
        if key_source == "byok":
            return round(self.byok_req * MICRO + tokens / 1000 * self.byok_1k * MICRO)
        if key_source == "selfhosted":
            return cost
        pct = self.markup_pct if tenant_markup is None else tenant_markup
        return round(cost * (1 + pct / 100))

    def hold_micro(self, attempts, upstream: dict, est_prompt: int, max_out: int, tenant_markup) -> int:
        out = max_out or self.default_out
        best = 0
        for p, m in attempts:
            src = upstream[p][1]
            best = max(best, self.charge_micro(self.cost_micro(m, est_prompt, out), src, tenant_markup, est_prompt + out))
        return best


class BillingHooks(GatewayHooks):
    def __init__(self, Session, vault: KeyVault, pricing: Pricing, state):
        self.Session, self.vault, self.pricing, self.state = Session, vault, pricing, state
        self.default_rpm = int(os.getenv("DEFAULT_KEY_RPM", "600"))
        self._ups_cache: tuple[float, dict] | None = None

    def invalidate_upstreams(self):
        self._ups_cache = None

    async def _platform_upstreams(self, s) -> dict:
        c = self._ups_cache
        if c and c[0] > time.monotonic():
            return c[1]
        ups = {}
        for u in await s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id.is_(None), UpstreamKey.active.is_(True))):
            ups[u.provider] = (self.vault.decrypt(u.enc_key), "selfhosted" if u.provider == "selfhosted" else "platform")
        self._ups_cache = (time.monotonic() + 30, ups)
        return ups

    async def authenticate(self, request: Request) -> Context:
        raw = bearer(request)
        if not raw:
            raise HTTPException(401, "缺少 API Key")
        async with self.Session() as s:
            ak = await s.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw), ApiKey.active.is_(True)))
            if not ak:
                raise HTTPException(401, "API Key 无效或已吊销")
            if ak.expires_at and aware(ak.expires_at) <= now():
                raise HTTPException(401, "API Key 已过期")
            if not ip_allowed(client_ip(request), split_csv(ak.ip_allowlist)):
                raise HTTPException(403, "当前 IP 不在该 Key 的白名单内")
            if ak.spend_limit_micro is not None and (ak.spent_micro or 0) >= ak.spend_limit_micro:
                raise HTTPException(402, "该 Key 已达到消费上限")
            t = await s.get(Tenant, ak.tenant_id)
            if not t or not t.active:
                raise HTTPException(403, "租户已停用")
            # 每 Key 每分钟限流（Redis 计数，多实例共享）
            limit = ak.rpm_limit or t.rpm_limit or self.default_rpm
            bucket = int(time.time() // 60)
            n = await self.state.incr(f"rl:key:{ak.id}:{bucket}", 65)
            if n > limit:
                RATE_LIMITED.labels("api_key").inc()
                raise HTTPException(429, f"请求过于频繁：该 Key 限制每分钟 {limit} 次", headers={"Retry-After": str(60 - int(time.time()) % 60)})
            if not ak.last_used_at or aware(ak.last_used_at) < now() - timedelta(seconds=60):
                ak.last_used_at = now()
                await s.commit()
            ups = dict(await self._platform_upstreams(s))
            for u in await s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id == t.id, UpstreamKey.active.is_(True))):
                ups[u.provider] = (self.vault.decrypt(u.enc_key), "byok")  # 租户自带 Key 优先
            if t.balance_micro <= 0:
                if self.pricing.byok_fee_pct > 0:
                    raise HTTPException(402, "余额不足，请充值")
                ups = {p: v for p, v in ups.items() if v[1] == "byok"}  # 余额耗尽时只能用自带 Key
                if not ups:
                    raise HTTPException(402, "余额不足，请充值或配置自带上游 Key")
            return Context(t.id, ak.id, ups, {"markup": t.markup_pct, "limit": t.monthly_token_limit, "hold": 0,
                                                     "allowed_models": split_csv(ak.allowed_models)})

    def allow_model(self, ctx: Context, model: str) -> bool:
        return model_allowed(model, ctx.extra.get("allowed_models") or [])

    async def check_quota(self, ctx: Context, est_prompt_tokens: int, model: str) -> None:
        if not ctx.extra.get("limit"):
            return
        start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self.Session() as s:
            used = await s.scalar(select(func.coalesce(func.sum(Usage.prompt_tokens + Usage.completion_tokens), 0))
                                  .where(Usage.tenant_id == ctx.tenant_id, Usage.created_at >= start)) or 0
        if used + est_prompt_tokens > ctx.extra["limit"]:
            raise HTTPException(429, "已超出本月 token 额度")

    async def reserve(self, ctx: Context, est_prompt_tokens: int, max_output_tokens: int, attempts: list) -> None:
        hold = self.pricing.hold_micro(attempts, ctx.upstream, est_prompt_tokens, max_output_tokens, ctx.extra.get("markup"))
        if hold <= 0:
            return
        async with self.Session() as s:
            res = await s.execute(update(Tenant).where(Tenant.id == ctx.tenant_id, Tenant.balance_micro >= hold)
                                  .values(balance_micro=Tenant.balance_micro - hold, reserved_micro=Tenant.reserved_micro + hold))
            await s.commit()
        if res.rowcount != 1:
            raise HTTPException(402, f"余额不足：本次请求需预授权 ${usd(hold):.6f}，请充值或调小 max_tokens")
        ctx.extra["hold"] = hold

    async def release(self, ctx: Context) -> None:
        hold = ctx.extra.get("hold", 0)
        if not hold:
            return
        ctx.extra["hold"] = 0
        async with self.Session() as s:
            await s.execute(update(Tenant).where(Tenant.id == ctx.tenant_id)
                            .values(balance_micro=Tenant.balance_micro + hold, reserved_micro=Tenant.reserved_micro - hold))
            await s.commit()

    async def settle(self, s, tenant_id: str, hold: int, charge: int) -> int:
        """在会话 s 内结算，返回实际扣费（微美元）。"""
        if charge <= hold:
            if hold:
                await s.execute(update(Tenant).where(Tenant.id == tenant_id).values(
                    balance_micro=Tenant.balance_micro + (hold - charge), reserved_micro=Tenant.reserved_micro - hold))
            return charge
        extra = charge - hold
        bal = await s.scalar(select(Tenant.balance_micro).where(Tenant.id == tenant_id).with_for_update())
        take = max(0, min(bal or 0, extra))
        await s.execute(update(Tenant).where(Tenant.id == tenant_id).values(
            balance_micro=Tenant.balance_micro - take, reserved_micro=Tenant.reserved_micro - hold))
        if take < extra:
            log.warning("charge exceeded hold and balance; capped", extra={"f_tenant": tenant_id, "f_shortfall_micro": extra - take})
        return hold + take

    async def record_usage(self, ctx, *, model, provider, key_source, usage, strategy, latency_ms, status):
        pt, ct = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
        cost = self.pricing.cost_micro(model, pt, ct)
        charge = self.pricing.charge_micro(cost, key_source, ctx.extra.get("markup"), pt + ct)
        hold, ctx.extra["hold"] = ctx.extra.get("hold", 0), 0
        async with self.Session() as s:
            charged = await self.settle(s, ctx.tenant_id, hold, charge)
            if ctx.api_key_id and charged:
                await s.execute(update(ApiKey).where(ApiKey.id == ctx.api_key_id).values(spent_micro=ApiKey.spent_micro + charged))
            s.add(Usage(tenant_id=ctx.tenant_id, api_key_id=ctx.api_key_id, model=model, provider=provider,
                        key_source=key_source, strategy=strategy, prompt_tokens=pt, completion_tokens=ct,
                        cost_micro=cost, charge_micro=charged, latency_ms=latency_ms, status=status))
            await s.commit()

    async def ready(self) -> dict:
        try:
            async with self.Session() as s:
                await s.execute(text("SELECT 1"))
            return {"database": True}
        except Exception:
            return {"database": False}
