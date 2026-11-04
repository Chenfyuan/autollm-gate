"""托管版入口：内核网关 + 多租户计费 + 租户控制台 + 管理后台。uvicorn autollm_admin.main:app"""
from __future__ import annotations
import logging, os
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from autollm_gate.gateway import create_app
from autollm_gate.router import load_config
from autollm_gate.state import make_state
from .alerts import Alerter
from .api_admin import SETTINGS_CHANNEL, build_admin, build_webhooks, ensure_bootstrap_admin
from .api_console import build_console
from .billing import BillingHooks, Pricing
from .crypto import KeyVault
from .db import create_all, make_engine, make_sessionmaker
from .payments import build_channels

log = logging.getLogger("autollm_admin")
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(Path(__file__).with_name("static"))))


def check_startup_config() -> None:
    """生产环境安全检查。"""
    if os.getenv("ENV", "").lower() != "production":
        return
    if os.getenv("ENABLE_MOCK_PAYMENT") == "1":
        raise RuntimeError("ENV=production 时禁止 ENABLE_MOCK_PAYMENT=1，拒绝启动")
    if len(os.getenv("SESSION_SECRET", "")) < 32:
        raise RuntimeError("ENV=production 时必须设置至少 32 位的 SESSION_SECRET，拒绝启动")


def build(database_url: str | None = None, master_key: str | None = None, state=None, auto_create: bool | None = None, **gw_kw):
    check_startup_config()
    engine = make_engine(database_url)
    Session = make_sessionmaker(engine)
    state = state or make_state()
    cfg = gw_kw.pop("config", None) or load_config()
    from autollm_gate.plugins import load_core
    pricing = (getattr(load_core(), "pricing_class", None) or Pricing)(cfg)
    hooks = BillingHooks(Session, KeyVault(master_key), pricing, state)
    channels = build_channels(os.getenv("ENABLE_MOCK_PAYMENT") == "1")
    alerter = Alerter(Session, state, pricing)
    if auto_create is None:
        auto_create = os.getenv("AUTO_CREATE_TABLES") == "1"

    async def on_settings(msg):
        hooks.invalidate_upstreams()
        await pricing.load(Session)

    async def startup(app):
        if auto_create:
            await create_all(engine)
        await ensure_bootstrap_admin(Session)
        await pricing.load(Session)
        await state.subscribe(SETTINGS_CHANNEL, on_settings)

    async def shutdown(app):
        await engine.dispose()

    app = create_app(hooks, config=cfg, state=state, lifespan_hooks=[(startup, shutdown), (alerter.start, alerter.stop)], **gw_kw)
    admin_router = build_admin(Session, hooks, state, alerter, channels)
    admin_router.gw_ref["gw"] = app.state.gateway
    app.include_router(admin_router)
    app.include_router(build_console(Session, hooks, state, channels))
    app.include_router(build_webhooks(Session, channels))
    app.state.Session, app.state.engine, app.state.hooks, app.state.alerter = Session, engine, hooks, alerter
    install_audit(app, Session)
    mount_frontend(app)
    return app


_AUDIT_SKIP = ("/api/admin/auth/", "/api/admin/keys/", "/api/admin/billing/webhook")


def install_audit(app, Session):
    """管理后台所有成功的写操作自动记审计（Key 相关接口自行记录更详细的内容）。"""
    from . import security as sec
    from .db import AdminUser
    from .governance import audit

    @app.middleware("http")
    async def _audit(request: Request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if (request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/admin/") and resp.status_code < 400
                and not path.startswith(_AUDIT_SKIP) and not (path.startswith("/api/admin/tenants/") and path.endswith("/keys"))):
            try:
                c = sec.read(request, sec.ADMIN_COOKIE, "admin")
                async with Session() as s:
                    a = await s.get(AdminUser, c["sub"])
                    parts = path[len("/api/admin/"):].split("/")
                    tid = parts[1] if parts[0] == "tenants" and len(parts) > 1 else None
                    await audit(s, request, "admin", a.email if a else c["sub"], f"{request.method.lower()} {parts[0]}",
                                "/".join(parts[1:]), tid)
                    await s.commit()
            except Exception:
                log.exception("audit failed")
        return resp


def mount_frontend(app):
    """前端（web/ 构建产物）由同一进程托管；SPA 路由统一回落到 index.html。"""
    index = STATIC_DIR / "index.html"
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request):
        if path.startswith(("api/", "v1/")):
            raise HTTPException(404, "Not Found")
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"message": "前端未构建：cd web && npm ci && npm run build"}, status_code=404)


app = build() if os.getenv("AUTOLLM_ADMIN_NO_AUTOBUILD") != "1" else None
