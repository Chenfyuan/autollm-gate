"""多租户鉴权、上游 Key 解析、额度检查与按 token 计费 —— 实现内核的 GatewayHooks。"""
from __future__ import annotations
import hashlib, os, secrets
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from sqlalchemy import func, select, update

from autollm_gate.hooks import Context, GatewayHooks, bearer
from .crypto import KeyVault
from .db import MICRO, ApiKey, Tenant, UpstreamKey, Usage, now


def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


def new_api_key() -> str:
    return "sk-lr-" + secrets.token_urlsafe(32)


class Pricing:
    """三种计费：
    - platform  ：平台统一上游 Key，按上游价 × (1 + 加价%) 扣余额
    - selfhosted：平台自部署开源模型，按 scoring.yaml 中的售价扣余额
    - byok      ：租户自带 Key，上游费用由租户自付，平台按「每请求 + 每千 token」收服务费（默认 0）
    """

    def __init__(self, cfg: dict, markup_pct: float | None = None, byok_fee_per_request: float | None = None,
                 byok_fee_per_1k_tokens: float | None = None):
        self.cfg = cfg
        env = lambda k, d: float(os.getenv(k, d))
        self.markup_pct = env("PLATFORM_MARKUP_PCT", "20") if markup_pct is None else markup_pct
        # 单位：美元
        self.byok_req = env("BYOK_FEE_PER_REQUEST_USD", "0") if byok_fee_per_request is None else byok_fee_per_request
        self.byok_1k = env("BYOK_FEE_PER_1K_TOKENS_USD", "0") if byok_fee_per_1k_tokens is None else byok_fee_per_1k_tokens

    SETTING_KEYS = {"platform_markup_pct": "markup_pct", "byok_fee_per_request_usd": "byok_req",
                    "byok_fee_per_1k_tokens_usd": "byok_1k"}

    def load(self, Session):
        """用数据库中的后台配置覆盖环境变量默认值。"""
        from .db import Setting
        with Session() as s:
            for row in s.query(Setting).all():
                if row.key in self.SETTING_KEYS:
                    setattr(self, self.SETTING_KEYS[row.key], float(row.value))
        return self

    def as_dict(self):
        return {k: getattr(self, a) for k, a in self.SETTING_KEYS.items()}

    @property
    def byok_fee_pct(self):  # 兼容：>0 表示 BYOK 也需要余额
        return 1 if (self.byok_req or self.byok_1k) else 0

    def cost_micro(self, model: str, pt: int, ct: int) -> int:
        m = self.cfg["models"].get(model)
        if not m:  # 未知模型按评分表最贵模型保守计价
            m = max(self.cfg["models"].values(), key=lambda v: v["price_out"])
        return round((pt * m["price_in"] + ct * m["price_out"]))  # $/1M token * token = 微美元

    def charge_micro(self, cost: int, key_source: str, tenant_markup: float | None, tokens: int = 0) -> int:
        if key_source == "byok":
            return round(self.byok_req * MICRO + tokens / 1000 * self.byok_1k * MICRO)
        if key_source == "selfhosted":
            return cost
        pct = self.markup_pct if tenant_markup is None else tenant_markup
        return round(cost * (1 + pct / 100))


class BillingHooks(GatewayHooks):
    def __init__(self, Session, vault: KeyVault, pricing: Pricing):
        self.Session, self.vault, self.pricing = Session, vault, pricing

    async def authenticate(self, request: Request, for_billing: bool = False) -> Context:
        raw = bearer(request)
        if not raw:
            raise HTTPException(401, "缺少 API Key")
        with self.Session() as s:
            ak = s.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw), ApiKey.active.is_(True)))
            if not ak:
                raise HTTPException(401, "API Key 无效")
            t = s.get(Tenant, ak.tenant_id)
            if not t or not t.active:
                raise HTTPException(403, "租户已停用")
            ak.last_used_at = now()
            ups = {}
            for u in s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id.is_(None), UpstreamKey.active.is_(True))):
                ups[u.provider] = (self.vault.decrypt(u.enc_key), "selfhosted" if u.provider == "selfhosted" else "platform")
            for u in s.scalars(select(UpstreamKey).where(UpstreamKey.tenant_id == t.id, UpstreamKey.active.is_(True))):
                ups[u.provider] = (self.vault.decrypt(u.enc_key), "byok")  # 租户自带 Key 优先
            s.commit()
            if t.balance_micro <= 0 and not for_billing:
                if self.pricing.byok_fee_pct > 0:
                    raise HTTPException(402, "余额不足，请充值")
                # 余额耗尽时只能使用租户自带 Key
                ups = {p: v for p, v in ups.items() if v[1] == "byok"}
                if not ups:
                    raise HTTPException(402, "余额不足，请充值或配置自带上游 Key")
            return Context(t.id, ak.id, ups, {"markup": t.markup_pct, "limit": t.monthly_token_limit})

    async def check_quota(self, ctx: Context, est_prompt_tokens: int, model: str) -> None:
        with self.Session() as s:
            t = s.get(Tenant, ctx.tenant_id)
            if t.monthly_token_limit:
                start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                used = s.scalar(select(func.coalesce(func.sum(Usage.prompt_tokens + Usage.completion_tokens), 0))
                                .where(Usage.tenant_id == t.id, Usage.created_at >= start)) or 0
                if used + est_prompt_tokens > t.monthly_token_limit:
                    raise HTTPException(429, "已超出本月 token 额度")

    async def record_usage(self, ctx, *, model, provider, key_source, usage, strategy, latency_ms, status):
        pt, ct = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
        cost = self.pricing.cost_micro(model, pt, ct)
        charge = self.pricing.charge_micro(cost, key_source, ctx.extra.get("markup"), pt + ct)
        with self.Session() as s:
            s.add(Usage(tenant_id=ctx.tenant_id, api_key_id=ctx.api_key_id, model=model, provider=provider,
                        key_source=key_source, strategy=strategy, prompt_tokens=pt, completion_tokens=ct,
                        cost_micro=cost, charge_micro=charge, latency_ms=latency_ms, status=status))
            if charge:  # 原子扣减，允许请求完成后小幅透支
                s.execute(update(Tenant).where(Tenant.id == ctx.tenant_id).values(balance_micro=Tenant.balance_micro - charge))
            s.commit()


def usd(micro: int) -> float:
    return round(micro / MICRO, 6)
