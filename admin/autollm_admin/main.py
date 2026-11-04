"""托管版入口：内核网关 + 多租户计费 + 管理后台。uvicorn autollm_admin.main:app"""
from __future__ import annotations
import os
from autollm_gate.gateway import create_app
from autollm_gate.router import load_config
from .api import build_admin
from .billing import BillingHooks, Pricing
from .crypto import KeyVault
from .db import make_sessionmaker
from .payments import build_channels


def check_startup_config() -> None:
    """生产环境安全检查：禁止启用模拟支付（否则任何人可伪造回调充值）。"""
    if os.getenv("ENV", "").lower() == "production" and os.getenv("ENABLE_MOCK_PAYMENT") == "1":
        raise RuntimeError("ENV=production 时禁止 ENABLE_MOCK_PAYMENT=1，拒绝启动")


def build(database_url: str | None = None, master_key: str | None = None, **gw_kw):
    check_startup_config()
    Session = make_sessionmaker(database_url)
    cfg = gw_kw.pop("config", None) or load_config()
    hooks = BillingHooks(Session, KeyVault(master_key), Pricing(cfg).load(Session))
    app = create_app(hooks, config=cfg, **gw_kw)
    app.include_router(build_admin(Session, hooks, build_channels(os.getenv("ENABLE_MOCK_PAYMENT") == "1")))
    app.state.Session = Session
    return app


app = build() if os.getenv("AUTOLLM_ADMIN_NO_AUTOBUILD") != "1" else None
