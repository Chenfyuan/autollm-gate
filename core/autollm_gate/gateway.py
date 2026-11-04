"""FastAPI 网关：/v1/chat/completions、/v1/messages、/v1/models。"""
from __future__ import annotations
import json, logging, time
from urllib.parse import quote
import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import anthropic_compat as ac
from .hooks import Context, GatewayHooks
from .providers import PROVIDER_CLASSES, UpstreamError
from .router import STRATEGIES, estimate_tokens, load_config, select
from .session import SessionStore, extract_session_id

log = logging.getLogger("autollm_gate")


def guess_provider(model: str) -> str | None:
    for prefix, p in (("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"), ("claude", "anthropic"),
                      ("gemini", "gemini"), ("deepseek", "deepseek")):
        if model.startswith(prefix):
            return p
    return None


class Gateway:
    def __init__(self, hooks: GatewayHooks | None = None, config: dict | None = None,
                 client: httpx.AsyncClient | None = None, base_urls: dict | None = None):
        self.hooks = hooks or GatewayHooks()
        self.cfg = config or load_config()
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
        self.base_urls = base_urls or {}
        self.sessions = SessionStore()

    def provider(self, name):
        return PROVIDER_CLASSES[name](self.client, self.base_urls.get(name))

    # ---------- 路由决策 ----------
    def plan(self, body: dict, ctx: Context, sid: str | None):
        avail = set(ctx.upstream)
        if not avail:
            raise HTTPException(503, "未配置任何上游 Key")
        sticky = self.sessions.get(sid) if sid else None
        is_auto = str(body.get("model", "auto")).startswith("auto")
        try:
            dec = select(body, self.cfg, avail)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(503, str(e))
        cands = list(dec.candidates)
        reason = dec.reason
        if is_auto and sticky and sticky in self.cfg["models"]:
            cands = [sticky] + [c for c in cands if c != sticky]
            reason = f"session-sticky; {reason}"
        attempts = []
        for m in cands:
            info = self.cfg["models"].get(m)
            p = info["provider"] if info else guess_provider(m)
            if p and p in avail:
                attempts.append((p, m))
        if not attempts:
            raise HTTPException(503, f"没有可用上游可服务模型 {body.get('model')}")
        return dec, attempts, reason

    def headers(self, dec, provider, model, reason, tried):
        return {"X-Router-Model": model, "X-Router-Provider": provider, "X-Router-Strategy": dec.strategy,
                "X-Router-Task": dec.task, "X-Router-Reason": quote(reason, safe=" ;=:.,-_/"),
                "X-Router-Attempts": str(tried)}

    def canonical(self, provider, model):
        return model

    # ---------- 核心执行 ----------
    async def run(self, request: Request, body: dict):
        """返回 (ctx, dec, reason, provider, model, tried, result_or_stream, is_stream)。"""
        ctx = await self.hooks.authenticate(request)
        if not body.get("messages"):
            raise HTTPException(400, "messages 不能为空")
        sid = extract_session_id(request.headers, body)
        dec, attempts, reason = self.plan(body, ctx, sid)
        await self.hooks.check_quota(ctx, estimate_tokens(body["messages"]), attempts[0][1])
        clean = {k: v for k, v in body.items() if k not in ("model", "stream", "stream_options", "metadata", "prompt_cache_key")}
        stream = bool(body.get("stream"))
        errors = []
        for i, (p, m) in enumerate(attempts[: 1 + self.cfg.get("max_fallbacks", 3) + 2]):
            key, _src = ctx.upstream[p]
            try:
                if stream:
                    gen = self.provider(p).stream(m, clean, key)
                    first = await gen.__anext__()  # 首包前失败可降级
                    result = (first, gen)
                else:
                    result = await self.provider(p).complete(m, clean, key)
            except StopAsyncIteration:
                errors.append(f"{p}/{m}: empty stream"); continue
            except UpstreamError as e:
                errors.append(str(e)); log.warning("upstream failed: %s", e)
                if not e.retryable:
                    break
                continue
            if sid and dec.strategy != "explicit":
                self.sessions.set(sid, self.canonical(p, m))
            r = reason if i == 0 else f"fallback#{i} after: {errors[-1][:80]}; {reason}"
            return ctx, dec, r, p, m, i + 1, result, stream
        raise HTTPException(502, {"error": "所有上游均失败", "attempts": errors})

    async def _record(self, ctx, dec, p, m, usage, t0, status="ok"):
        try:
            await self.hooks.record_usage(ctx, model=self.canonical(p, m), provider=p, key_source=ctx.upstream[p][1],
                                          usage=usage or {}, strategy=dec.strategy, latency_ms=int((time.time() - t0) * 1000), status=status)
        except Exception:  # 计量失败不影响响应，但必须记录
            log.exception("record_usage failed")

    def build(self) -> APIRouter:
        r = APIRouter()

        @r.get("/v1/models")
        async def models(request: Request):
            await self.hooks.authenticate(request)
            now = int(time.time())
            data = [{"id": "auto", "object": "model", "created": now, "owned_by": "AutoLLM Gate"}]
            data += [{"id": f"auto:{s}", "object": "model", "created": now, "owned_by": "AutoLLM Gate"} for s in STRATEGIES]
            data += [{"id": k, "object": "model", "created": now, "owned_by": v["provider"]} for k, v in self.cfg["models"].items()]
            return {"object": "list", "data": data}

        @r.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            t0 = time.time()
            ctx, dec, reason, p, m, tried, res, stream = await self.run(request, body)
            hdr = self.headers(dec, p, m, reason, tried)
            if not stream:
                await self._record(ctx, dec, p, m, res.get("usage"), t0)
                return JSONResponse(res, headers=hdr)
            first, gen = res
            usage = {}

            async def sse():
                try:
                    for c in [first]:
                        if c.get("usage"): usage.update(c["usage"])
                        yield f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
                    async for c in gen:
                        if c.get("usage"): usage.update(c["usage"])
                        yield f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                finally:
                    await self._record(ctx, dec, p, m, usage, t0)
            return StreamingResponse(sse(), media_type="text/event-stream", headers=hdr)

        @r.post("/v1/messages")
        async def messages(request: Request):
            abody = await request.json()
            body = ac.messages_to_openai(abody)
            body["stream"] = bool(abody.get("stream"))
            t0 = time.time()
            ctx, dec, reason, p, m, tried, res, stream = await self.run(request, body)
            hdr = self.headers(dec, p, m, reason, tried)
            if not stream:
                await self._record(ctx, dec, p, m, res.get("usage"), t0)
                return JSONResponse(ac.openai_to_message(res, self.canonical(p, m)), headers=hdr)
            first, gen = res
            usage = {}

            async def chain():
                yield first
                async for c in gen:
                    yield c

            async def sse():
                try:
                    async for ev in ac.openai_stream_to_anthropic(chain(), self.canonical(p, m), usage):
                        yield ev
                finally:
                    await self._record(ctx, dec, p, m, usage, t0)
            return StreamingResponse(sse(), media_type="text/event-stream", headers=hdr)

        @r.post("/v1/messages/count_tokens")
        async def count_tokens(request: Request):
            await self.hooks.authenticate(request)
            b = await request.json()
            return {"input_tokens": estimate_tokens(ac.messages_to_openai(b)["messages"])}

        @r.get("/healthz")
        async def health():
            return {"ok": True}
        return r


def create_app(hooks: GatewayHooks | None = None, **kw) -> FastAPI:
    app = FastAPI(title="AutoLLM Gate", version="0.1.0")
    gw = Gateway(hooks, **kw)
    app.state.gateway = gw
    app.include_router(gw.build())

    @app.exception_handler(HTTPException)
    async def _h(request, exc: HTTPException):
        return JSONResponse({"error": exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))
    return app
