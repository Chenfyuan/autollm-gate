"""FastAPI 网关：/v1/chat/completions、/v1/messages、/v1/responses、/v1/models，以及 /healthz /readyz /metrics。"""
from __future__ import annotations
import json, logging, os, time
from contextlib import asynccontextmanager
from urllib.parse import quote
import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import anthropic_compat as ac
from . import responses_compat as rc
from . import metrics as M
from .breaker import Breakers
from .hooks import Context, GatewayHooks
from .logging_setup import fields, setup_logging
from .providers import PROVIDER_CLASSES, UpstreamError
from .router import STRATEGIES, estimate_tokens, load_config, select as default_select
from .plugins import load_core
from .session import SessionStore, extract_session_id
from .state import make_state

log = logging.getLogger("autollm_gate")


def guess_provider(model: str) -> str | None:
    for prefix, p in (("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"), ("codex", "openai"),
                      ("claude", "anthropic"), ("gemini", "gemini"), ("deepseek", "deepseek")):
        if model.startswith(prefix):
            return p
    return None


class Gateway:
    def __init__(self, hooks: GatewayHooks | None = None, config: dict | None = None,
                 client: httpx.AsyncClient | None = None, base_urls: dict | None = None, state=None, breakers: Breakers | None = None):
        self.hooks = hooks or GatewayHooks()
        self.cfg = config or load_config()
        timeout = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "600"))
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=float(os.getenv("UPSTREAM_CONNECT_TIMEOUT_SECONDS", "10"))),
                                                  limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200))
        self.base_urls = base_urls or {}
        self.state = state or make_state()
        self.sessions = SessionStore(self.state)
        self.breakers = breakers or Breakers()
        self.core = load_core()
        self.select = getattr(self.core, "select", None) or default_select

    def provider(self, name):
        return PROVIDER_CLASSES[name](self.client, self.base_urls.get(name))

    # ---------- 路由决策 ----------
    async def plan(self, body: dict, ctx: Context, sid: str | None):
        avail = set(ctx.upstream)
        if not avail:
            raise HTTPException(503, "未配置任何上游 Key")
        sticky = await self.sessions.get(sid, ctx.tenant_id) if sid else None
        is_auto = str(body.get("model", "auto")).startswith("auto")
        try:
            dec = self.select(body, self.cfg, avail)
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
            if info and info.get("enabled") is False:
                continue
            p = info["provider"] if info else guess_provider(m)
            if p and p in avail:
                attempts.append((p, m))
        if not attempts:
            raise HTTPException(503, f"没有可用上游可服务模型 {body.get('model')}")
        return dec, attempts, reason

    def _observe(self, p, ok, latency):
        fn = getattr(self.core, "observe", None)
        if fn:
            try:
                fn(p, ok, latency)
            except Exception:
                log.exception("core observe failed")

    # ---------- 跨副本共享熔断：某副本熔断后写入 Redis，其他副本在冷却期内同样跳过该上游 ----------
    async def _shared_open(self, p) -> bool:
        try:
            return bool(await self.state.get(f"breaker:open:{p}"))
        except Exception:
            return False

    async def _share_open(self, p, cooldown):
        try:
            await self.state.set(f"breaker:open:{p}", "1", ttl=max(1, int(cooldown)))
        except Exception:
            log.warning("share breaker state failed")

    def headers(self, dec, provider, model, reason, tried):
        return {"X-Router-Model": model, "X-Router-Provider": provider, "X-Router-Strategy": dec.strategy,
                "X-Router-Task": dec.task, "X-Router-Reason": quote(reason, safe=" ;=:.,-_/#"),
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
        dec, attempts, reason = await self.plan(body, ctx, sid)
        if dec.strategy == "explicit" and not self.hooks.allow_model(ctx, str(body.get("model"))):
            attempts = []
        attempts = [(p, m) for p, m in attempts if self.hooks.allow_model(ctx, m)]
        if not attempts:
            raise HTTPException(403, f"该 API Key 无权使用模型 {body.get('model')}")
        est = estimate_tokens(body["messages"])
        await self.hooks.check_quota(ctx, est, attempts[0][1])
        max_out = int(body.get("max_tokens") or body.get("max_completion_tokens") or 0)
        attempts = attempts[: 1 + self.cfg.get("max_fallbacks", 3) + 2]
        await self.hooks.reserve(ctx, est, max_out, attempts)
        clean = {k: v for k, v in body.items() if k not in ("model", "stream", "stream_options", "metadata", "prompt_cache_key")}
        stream = bool(body.get("stream"))
        errors, tried = [], 0
        try:
            for p, m in attempts:
                br = self.breakers.get(p)
                if br.state == "closed" and await self._shared_open(p):
                    errors.append(f"{p}/{m}: circuit open (shared)")
                    continue
                if not br.allow():
                    errors.append(f"{p}/{m}: circuit open")
                    continue
                key, _src = ctx.upstream[p]
                t0 = time.monotonic()
                tried += 1
                try:
                    if stream:
                        gen = self.provider(p).stream(m, clean, key)
                        first = await gen.__anext__()  # 首包前失败可降级
                        result = (first, gen)
                    else:
                        result = await self.provider(p).complete(m, clean, key)
                except StopAsyncIteration:
                    br.failure(); await M.record_upstream(self.state, p, False, time.monotonic() - t0); self._observe(p, False, time.monotonic() - t0)
                    errors.append(f"{p}/{m}: empty stream"); continue
                except UpstreamError as e:
                    # 4xx 参数错误不是上游故障，不计入熔断
                    upstream_fault = e.status in (0, 408, 429) or e.status >= 500
                    if upstream_fault:
                        br.failure()
                        if br.state == "open":
                            await self._share_open(p, br.cooldown)
                    await M.record_upstream(self.state, p, not upstream_fault, time.monotonic() - t0); self._observe(p, not upstream_fault, time.monotonic() - t0)
                    M.BREAKER.labels(p).set(0 if br.state == "closed" else 1)
                    errors.append(str(e))
                    log.warning("upstream failed", extra=fields(provider=p, model=m, status=e.status, detail=e.detail[:200]))
                    M.FAILOVERS.labels(p).inc()
                    if not e.retryable:
                        break
                    continue
                br.success(); M.BREAKER.labels(p).set(0)
                await M.record_upstream(self.state, p, True, time.monotonic() - t0); self._observe(p, True, time.monotonic() - t0)
                if sid and dec.strategy != "explicit":
                    await self.sessions.set(sid, self.canonical(p, m), ctx.tenant_id)
                r = reason if not errors else f"fallback#{len(errors)} after: {errors[-1][:80]}; {reason}"
                return ctx, dec, r, p, m, tried, result, stream
        except BaseException:
            await self.hooks.release(ctx)
            raise
        await self.hooks.release(ctx)
        if tried == 0:
            raise HTTPException(503, {"message": "所有候选上游均处于熔断状态，请稍后重试", "attempts": errors})
        raise HTTPException(502, {"message": "所有上游均失败", "attempts": errors})

    async def _record(self, ctx, dec, p, m, usage, t0, status="ok"):
        usage = usage or {}
        try:
            M.TOKENS.labels(m, "prompt").inc(int(usage.get("prompt_tokens", 0) or 0))
            M.TOKENS.labels(m, "completion").inc(int(usage.get("completion_tokens", 0) or 0))
            await self.hooks.record_usage(ctx, model=self.canonical(p, m), provider=p, key_source=ctx.upstream[p][1],
                                          usage=usage, strategy=dec.strategy, latency_ms=int((time.time() - t0) * 1000), status=status)
        except Exception:  # 计量失败不影响响应，但必须记录
            log.exception("record_usage failed")

    def _stream_response(self, ctx, dec, p, m, res, t0, hdr, convert):
        first, gen = res
        usage: dict = {}

        async def chain():
            yield first
            async for c in gen:
                yield c

        async def sse():
            status = "ok"
            try:
                async for ev in convert(chain(), usage):
                    yield ev
            except Exception:
                status = "stream_error"
                log.exception("stream interrupted")
            finally:
                await self._record(ctx, dec, p, m, usage, t0, status)
        return StreamingResponse(sse(), media_type="text/event-stream", headers={**hdr, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def build(self) -> APIRouter:
        r = APIRouter()

        @r.get("/v1/models")
        async def models(request: Request):
            await self.hooks.authenticate(request)
            now = int(time.time())
            data = [{"id": "auto", "object": "model", "created": now, "owned_by": "AutoLLM Gate"}]
            data += [{"id": f"auto:{s}", "object": "model", "created": now, "owned_by": "AutoLLM Gate"} for s in STRATEGIES]
            data += [{"id": k, "object": "model", "created": now, "owned_by": v["provider"]} for k, v in self.cfg["models"].items()
                     if v.get("enabled") is not False]
            return {"object": "list", "data": data}

        @r.post("/v1/embeddings")
        async def embeddings(request: Request):
            """向量接口：直通 OpenAI 兼容上游（openai / deepseek / selfhosted 等）。"""
            body = await request.json()
            t0 = time.time()
            ctx = await self.hooks.authenticate(request)
            m = str(body.get("model") or "")
            if not m or body.get("input") in (None, "", []):
                raise HTTPException(400, "model 与 input 不能为空")
            info = self.cfg["models"].get(m) or {}
            p = info.get("provider") or guess_provider(m) or "openai"
            if p not in ctx.upstream:
                raise HTTPException(503, f"未配置上游 {p}")
            if not hasattr(self.provider(p), "embeddings"):
                raise HTTPException(400, f"上游 {p} 暂不支持 embeddings")
            if not self.hooks.allow_model(ctx, m):
                raise HTTPException(403, f"该 API Key 无权使用模型 {m}")
            inp = body["input"]
            est = max(1, len(json.dumps(inp, ensure_ascii=False)) // 3)
            await self.hooks.check_quota(ctx, est, m)
            await self.hooks.reserve(ctx, est, 1, [(p, m)])
            try:
                res = await self.provider(p).embeddings(m, {k: v for k, v in body.items() if k != "model"}, ctx.upstream[p][0])
            except UpstreamError as e:
                await self.hooks.release(ctx)
                raise HTTPException(502, {"message": "上游失败", "attempts": [str(e)]})
            except BaseException:
                await self.hooks.release(ctx)
                raise
            u = res.get("usage") or {}
            usage = {"prompt_tokens": int(u.get("prompt_tokens") or u.get("total_tokens") or est), "completion_tokens": 0}
            from .router import Decision
            dec = Decision(m, [m], "explicit", "embeddings", "embeddings")
            await self._record(ctx, dec, p, m, usage, t0)
            return JSONResponse(res, headers={"X-Router-Model": m, "X-Router-Provider": p})

        @r.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            t0 = time.time()
            ctx, dec, reason, p, m, tried, res, stream = await self.run(request, body)
            hdr = self.headers(dec, p, m, reason, tried)
            if not stream:
                await self._record(ctx, dec, p, m, res.get("usage"), t0)
                return JSONResponse(res, headers=hdr)

            async def conv(chunks, usage):
                async for c in chunks:
                    if c.get("usage"):
                        usage.update(c["usage"])
                    yield f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return self._stream_response(ctx, dec, p, m, res, t0, hdr, conv)

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
            return self._stream_response(ctx, dec, p, m, res, t0, hdr,
                                         lambda ch, u: ac.openai_stream_to_anthropic(ch, self.canonical(p, m), u))

        @r.post("/v1/responses")
        async def responses(request: Request):
            rbody = await request.json()
            body = rc.responses_to_chat(rbody)
            t0 = time.time()
            ctx, dec, reason, p, m, tried, res, stream = await self.run(request, body)
            hdr = self.headers(dec, p, m, reason, tried)
            if not stream:
                await self._record(ctx, dec, p, m, res.get("usage"), t0)
                return JSONResponse(rc.chat_to_response(res, self.canonical(p, m)), headers=hdr)
            return self._stream_response(ctx, dec, p, m, res, t0, hdr,
                                         lambda ch, u: rc.chat_stream_to_responses(ch, self.canonical(p, m), u))

        @r.post("/v1/messages/count_tokens")
        async def count_tokens(request: Request):
            await self.hooks.authenticate(request)
            b = await request.json()
            return {"input_tokens": estimate_tokens(ac.messages_to_openai(b)["messages"])}

        @r.get("/healthz")
        async def health():
            """存活检查：进程在即返回 200。"""
            return {"ok": True, "core": getattr(self.core, "name", "custom")}

        @r.get("/readyz")
        async def ready():
            """就绪检查：数据库 / Redis 等依赖可用才返回 200，负载均衡据此摘除实例。"""
            checks = {"state": await self.state.ping()}
            try:
                checks.update(await self.hooks.ready())
            except Exception:
                checks["hooks"] = False
            ok = all(checks.values())
            return JSONResponse({"ok": ok, "checks": checks, "breakers": self.breakers.snapshot()}, status_code=200 if ok else 503)

        @r.get("/metrics")
        async def metrics(request: Request):
            tok = os.getenv("METRICS_TOKEN")
            if tok and request.headers.get("authorization") != f"Bearer {tok}":
                raise HTTPException(401, "metrics 需要令牌")
            data, ctype = M.render()
            return Response(data, media_type=ctype)
        return r


def create_app(hooks: GatewayHooks | None = None, lifespan_hooks: list | None = None, **kw) -> FastAPI:
    setup_logging()
    gw = Gateway(hooks, **kw)
    extra = lifespan_hooks or []

    @asynccontextmanager
    async def lifespan(app):
        for start, _ in extra:
            await start(app)
        yield
        for _, stop in reversed(extra):
            await stop(app)
        await gw.state.close()

    app = FastAPI(title="AutoLLM Gate", version="0.3.0", lifespan=lifespan)
    app.state.gateway = gw

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        t0 = time.time()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra=fields(path=request.url.path))
            resp = JSONResponse({"error": {"message": "服务器内部错误"}}, status_code=500)
        path = request.url.path
        ep = path if path.startswith("/v1/") or path in ("/healthz", "/readyz", "/metrics") else ("/api" if path.startswith("/api/") else "static")
        M.REQUESTS.labels(ep, str(resp.status_code)).inc()
        if ep not in ("static", "/healthz", "/readyz", "/metrics"):
            log.info("request", extra=fields(method=request.method, path=path, status=resp.status_code,
                                             ms=int((time.time() - t0) * 1000), model=resp.headers.get("x-router-model")))
        return resp

    app.include_router(gw.build())

    @app.exception_handler(HTTPException)
    async def _h(request, exc: HTTPException):
        return JSONResponse({"error": exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))
    return app
