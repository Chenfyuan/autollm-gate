"""内核与商业层之间的扩展点。开源内核自带一个基于环境变量的单租户实现。"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from fastapi import HTTPException, Request

ENV_KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY", "selfhosted": "SELFHOSTED_API_KEY"}


@dataclass
class Context:
    tenant_id: str
    api_key_id: str | None = None
    # provider -> (上游 key, 来源 "byok" | "selfhosted" | "platform")
    upstream: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


class GatewayHooks:
    async def authenticate(self, request: Request) -> Context:
        expected = os.getenv("ROUTER_API_KEY")
        if expected and bearer(request) != expected:
            raise HTTPException(401, "invalid api key")
        return Context("default", upstream={p: (os.environ[e], "byok") for p, e in ENV_KEYS.items() if os.getenv(e)})

    async def check_quota(self, ctx: Context, est_prompt_tokens: int, model: str) -> None:
        return None

    async def reserve(self, ctx: Context, est_prompt_tokens: int, max_output_tokens: int, attempts: list) -> None:
        """调用上游前预授权（冻结）余额。商业层实现原子冻结，不足则抛 402。"""
        return None

    async def release(self, ctx: Context) -> None:
        """所有上游失败时释放预授权。"""
        return None

    async def record_usage(self, ctx: Context, *, model: str, provider: str, key_source: str, usage: dict,
                           strategy: str, latency_ms: int, status: str) -> None:
        """记录用量并结算（扣实际费用、退回多冻结的部分）。"""
        return None

    async def ready(self) -> dict:
        """就绪检查：返回各依赖状态 {name: bool}。"""
        return {}
