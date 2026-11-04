"""v0.2 商业层：并发预授权不透支、租户自助控制台、每 Key 限流、跨实例配置广播、告警 Webhook。"""
import asyncio, json, os
import httpx, pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from autollm_admin.main import build
from autollm_admin.billing import BillingHooks, Pricing
from autollm_admin.crypto import KeyVault
from autollm_admin.db import MICRO, Tenant, Usage, create_all, make_engine, make_sessionmaker
from autollm_gate.hooks import Context
from autollm_gate.router import load_config
from autollm_gate.state import MemoryState, RedisState
from test_admin_billing import ADMIN_EMAIL, ADMIN_PW, H, admin_login, chat, tenant


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k, v in {"ENABLE_MOCK_PAYMENT": "1", "ENV": "test", "PLATFORM_MARKUP_PCT": "20", "ADMIN_BOOTSTRAP_EMAIL": ADMIN_EMAIL,
                 "ADMIN_BOOTSTRAP_PASSWORD": ADMIN_PW, "ALERTS_DISABLED": "1", "SESSION_SECRET": "s" * 40}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("REDIS_URL", raising=False)
    return tmp_path


@pytest.fixture
def app(env, client_factory, master_key):
    with TestClient(build(f"sqlite:///{env}/t.db", master_key, auto_create=True, client=client_factory())) as c:
        yield c


# ---------------- 并发预授权 ----------------
DB_URLS = [None] + ([os.environ["TEST_DATABASE_URL"]] if os.getenv("TEST_DATABASE_URL") else [])


@pytest.mark.parametrize("db_url", DB_URLS, ids=lambda u: "postgres" if u else "sqlite")
def test_concurrent_reserve_never_overdraws(tmp_path, master_key, db_url):
    """余额只够 10 次预授权，100 个并发请求同时预授权 → 恰好 10 个成功，余额不为负；结算后不重复扣费。"""
    async def go():
        engine = make_engine(db_url or f"sqlite:///{tmp_path}/c.db")
        await create_all(engine)
        S = make_sessionmaker(engine)
        pricing = Pricing(load_config())
        hooks = BillingHooks(S, KeyVault(master_key), pricing, MemoryState())
        attempts = [("openai", "gpt-4o")]
        ups = {"openai": ("k", "platform")}
        hold = pricing.hold_micro(attempts, ups, 10, 100, None)
        async with S() as s:
            t = Tenant(name="并发测试", balance_micro=hold * 10)
            s.add(t); await s.commit()
        ctxs = [Context(t.id, None, ups, {"markup": None, "hold": 0}) for _ in range(100)]

        async def one(c):
            try:
                await hooks.reserve(c, 10, 100, attempts)
                return True
            except Exception as e:
                assert getattr(e, "status_code", None) == 402, e
                return False
        ok = await asyncio.gather(*[one(c) for c in ctxs])
        assert sum(ok) == 10
        async with S() as s:
            t2 = await s.get(Tenant, t.id)
            assert t2.balance_micro == 0 and t2.reserved_micro == hold * 10
        # 并发结算：每个成功请求实际用 10/5 token
        winners = [c for c, k in zip(ctxs, ok) if k]
        await asyncio.gather(*[hooks.record_usage(c, model="gpt-4o", provider="openai", key_source="platform",
                                                  usage={"prompt_tokens": 10, "completion_tokens": 5}, strategy="explicit",
                                                  latency_ms=1, status="ok") for c in winners])
        # 重复结算同一个 ctx 不会再次扣费（hold 已清零）
        await hooks.record_usage(winners[0], model="gpt-4o", provider="openai", key_source="platform", usage={}, strategy="x", latency_ms=1, status="ok")
        async with S() as s:
            t3 = await s.get(Tenant, t.id)
            charged = sum((await s.scalars(select(Usage.charge_micro).where(Usage.tenant_id == t.id))).all())
        assert t3.reserved_micro == 0 and t3.balance_micro >= 0
        assert t3.balance_micro + charged == hold * 10  # 资金守恒：无重复扣费、无凭空消失
        await engine.dispose()
    asyncio.run(go())


def test_settle_never_negative_when_actual_exceeds_hold(tmp_path, master_key):
    async def go():
        engine = make_engine(f"sqlite:///{tmp_path}/c.db"); await create_all(engine)
        S = make_sessionmaker(engine)
        hooks = BillingHooks(S, KeyVault(master_key), Pricing(load_config()), MemoryState())
        async with S() as s:
            t = Tenant(name="x", balance_micro=1000); s.add(t); await s.commit()
        c = Context(t.id, None, {"openai": ("k", "platform")}, {"markup": None, "hold": 0})
        await hooks.reserve(c, 1, 1, [("openai", "gpt-4o")])
        await hooks.record_usage(c, model="gpt-4o", provider="openai", key_source="platform",
                                 usage={"prompt_tokens": 100000, "completion_tokens": 100000}, strategy="x", latency_ms=1, status="ok")
        async with S() as s:
            t2 = await s.get(Tenant, t.id)
            u = (await s.scalars(select(Usage))).one()
        assert t2.balance_micro == 0 and t2.reserved_micro == 0 and u.charge_micro == 1000
        await engine.dispose()
    asyncio.run(go())


def test_reservation_released_when_all_upstreams_fail(app, upstream):
    admin_login(app)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    upstream.fail = {"openai"}
    assert chat(app, h).status_code == 502
    d = app.get(f"/api/admin/tenants/{tid}").json()
    assert d["balance_usd"] == 1 and d["reserved_usd"] == 0


def test_large_max_tokens_needs_enough_balance(app):
    admin_login(app)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 0.01}, headers=H)
    r = chat(app, h, max_tokens=100000)  # 100k * $10/M * 1.2 = $1.2 > $0.01
    assert r.status_code == 402 and "预授权" in r.text
    assert chat(app, h, max_tokens=100).status_code == 200


# ---------------- 租户控制台 ----------------
def test_tenant_signup_login_keys_usage_flow(app, upstream):
    c = app
    r = c.post("/api/auth/signup", json={"email": "Dev@Example.com", "password": "abc", "company": "星河"})
    assert r.status_code == 422
    assert c.post("/api/auth/signup", json={"email": "dev@example.com", "password": "Passw0rd!", "company": "星河"}).status_code == 200
    assert c.post("/api/auth/signup", json={"email": "dev@example.com", "password": "Passw0rd!", "company": "星河"}).status_code == 409
    me = c.get("/api/me").json()
    assert me["tenant"]["name"] == "星河" and me["user"]["email"] == "dev@example.com"
    k = c.post("/api/console/keys", json={"name": "生产"}, headers=H).json()
    assert k["api_key"].startswith("sk-lr-")
    assert "api_key" not in c.get("/api/console/keys").json()[0]  # 明文只显示一次
    # 充值（mock）
    tp = c.post("/api/console/topups", json={"amount_usd": 10, "channel": "mock"}, headers=H).json()
    c.post(f"/api/console/topups/{tp['id']}/mock-pay", headers=H)
    c.post(f"/api/console/topups/{tp['id']}/mock-pay", headers=H)  # 幂等
    assert c.get("/api/me").json()["tenant"]["balance_usd"] == 10
    # 平台 Key 由管理员配置
    with TestClient(app.app) as a:
        admin_login(a)
        a.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    hk = {"Authorization": f"Bearer {k['api_key']}"}
    assert chat(c, hk).status_code == 200
    assert c.post("/v1/responses", json={"model": "gpt-4o", "input": "hi"}, headers=hk).status_code == 200
    ov = c.get("/api/console/overview").json()
    assert ov["month"]["requests"] == 2 and ov["models"][0]["model"] == "gpt-4o"
    bill = c.get("/api/console/billing").json()
    assert bill["total"] == 2 and bill["items"][0]["key_name"] == "生产"
    u = c.get("/api/console/usage?days=7").json()
    assert len(u["daily"]) == 7 and "gpt-4o" in u["by_model_daily"]["models"]
    # 吊销
    c.delete(f"/api/console/keys/{k['id']}", headers=H)
    assert chat(c, hk).status_code == 401
    # 登出再登录
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "dev@example.com", "password": "bad-pass-1"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "DEV@example.com", "password": "Passw0rd!"}).status_code == 200


def test_tenant_cannot_touch_other_tenant_key(app):
    with TestClient(app.app) as a, TestClient(app.app) as b:
        a.post("/api/auth/signup", json={"email": "a@x.com", "password": "Passw0rd!", "company": "A"})
        b.post("/api/auth/signup", json={"email": "b@x.com", "password": "Passw0rd!", "company": "B"})
        k = a.post("/api/console/keys", json={"name": "a"}, headers=H).json()
        assert b.delete(f"/api/console/keys/{k['id']}", headers=H).status_code == 404
        assert b.get("/api/admin/tenants").status_code == 401  # 租户会话不能访问后台


def test_signup_rate_limited(app):
    codes = [app.post("/api/auth/signup", json={"email": f"u{i}@x.com", "password": "Passw0rd!", "company": "C"}).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_per_key_rate_limit(app, monkeypatch):
    admin_login(app)
    tid, h = tenant(app)
    app.patch(f"/api/admin/tenants/{tid}", json={"rpm_limit": 3}, headers=H)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    codes = [chat(app, h).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


# ---------------- 跨实例配置广播（Redis） ----------------
def test_settings_broadcast_across_instances(env, client_factory, master_key):
    fakeredis = pytest.importorskip("fakeredis")
    server = fakeredis.FakeServer()
    mk = lambda: RedisState(client=fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    a1 = build(f"sqlite:///{env}/b.db", master_key, auto_create=True, client=client_factory(), state=mk())
    a2 = build(f"sqlite:///{env}/b.db", master_key, auto_create=True, client=client_factory(), state=mk())
    with TestClient(a1) as c1, TestClient(a2) as c2:
        admin_login(c1); admin_login(c2)
        assert c2.get("/api/admin/settings").json()["platform_markup_pct"] == 20
        c1.put("/api/admin/settings", json={"platform_markup_pct": 75}, headers=H)
        import time
        for _ in range(50):
            if c2.get("/api/admin/settings").json()["platform_markup_pct"] == 75:
                break
            time.sleep(0.05)
        assert c2.get("/api/admin/settings").json()["platform_markup_pct"] == 75
        # 会话粘性 / 限流计数也走同一个 Redis
        assert c2.app.state.gateway.state.kind == "redis"


# ---------------- 告警 ----------------
def test_alert_webhook_low_balance_and_error_spike(app, upstream):
    got = []
    hook_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (got.append(json.loads(r.content)), httpx.Response(200))[1]))
    alerter = app.app.state.alerter
    alerter.client = hook_client
    admin_login(app)
    app.put("/api/admin/settings", json={"alert_webhook_url": "http://hook.local/x", "alert_webhook_format": "feishu",
                                        "alert_low_balance_usd": 5, "alert_min_requests": 3, "alert_error_rate_pct": 50}, headers=H)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.put("/api/admin/upstreams", json={"provider": "deepseek", "api_key": "sk-platform-5678"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    upstream.modes["openai"] = "503"
    for _ in range(4):
        assert chat(app, h).status_code == 200  # 自动降级到 deepseek
    fired = app.post("/api/admin/alerts/evaluate", headers=H).json()["fired"]
    assert any("openai" in f for f in fired) and any("余额不足" in f for f in fired)
    assert got and got[0]["msg_type"] == "text"
    # 冷却期内不重复发送
    assert app.post("/api/admin/alerts/evaluate", headers=H).json()["fired"] == []
    mon = app.get("/api/admin/monitoring").json()
    o = [p for p in mon["providers"] if p["provider"] == "openai"][0]
    assert o["err"] >= 4 and o["error_rate"] == 1.0 and len(mon["alerts"]) >= 2
    assert app.post("/api/admin/alerts/test", headers=H).json()["delivered"] is True
