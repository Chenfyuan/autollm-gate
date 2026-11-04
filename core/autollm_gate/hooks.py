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

    async def record_usage(self, ctx: Context, *, model: str, provider: str, key_source: str, usage: dict,
                           strategy: str, latency_ms: int, status: str) -> None:
        return None
