"""商业层：管理员登录、租户、上游 Key 加密与掩码、计费加价、BYOK、充值。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from autollm_admin.main import build

H = {"X-Requested-With": "autollm"}
ADMIN_EMAIL, ADMIN_PW = "root@example.com", "S3cure-pass"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_MOCK_PAYMENT", "1")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("PLATFORM_MARKUP_PCT", "20")
    monkeypatch.setenv("BYOK_FEE_PER_REQUEST_USD", "0")
    monkeypatch.setenv("BYOK_FEE_PER_1K_TOKENS_USD", "0")
    monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", ADMIN_PW)
    monkeypatch.setenv("ALERTS_DISABLED", "1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    return tmp_path


@pytest.fixture
def make_app(env, client_factory, master_key):
    def f(**kw):
        return TestClient(build(f"sqlite:///{env}/t.db", master_key, auto_create=True, client=client_factory(), **kw))
    return f


@pytest.fixture
def app(make_app):
    with make_app() as c:
        yield c


def admin_login(c):
    r = c.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return c


def tenant(c, **kw):
    t = c.post("/api/admin/tenants", json={"name": "Acme 科技", **kw}, headers=H).json()
    k = c.post(f"/api/admin/tenants/{t['id']}/keys", json={"name": "k"}, headers=H).json()["api_key"]
    return t["id"], {"Authorization": f"Bearer {k}"}


def chat(c, h, model="gpt-4o", **kw):
    return c.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}], **kw}, headers=h)


def test_admin_auth_required_and_csrf(app):
    assert app.get("/api/admin/tenants").status_code == 401
    assert app.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pass1"}).status_code == 401
    admin_login(app)
    assert app.get("/api/admin/tenants").status_code == 200
    # 有 Cookie 但缺少 CSRF 头的写操作被拒绝
    assert app.post("/api/admin/tenants", json={"name": "x"}).status_code == 403
    app.post("/api/admin/auth/logout")
    assert app.get("/api/admin/tenants").status_code == 401


def test_admin_password_is_hashed(app):
    from autollm_admin.db import AdminUser
    import asyncio
    async def go():
        async with app.app.state.Session() as s:
            return (await s.scalars(select(AdminUser))).one()
    a = app.portal.call(go) if hasattr(app, "portal") and app.portal else asyncio.run(go())
    assert a.password_hash.startswith("$argon2id$") and ADMIN_PW not in a.password_hash


def test_multiple_admins_and_disable(app, make_app):
    admin_login(app)
    r = app.post("/api/admin/admins", json={"email": "ops@example.com", "name": "运维", "password": "short"}, headers=H)
    assert r.status_code == 422
    r = app.post("/api/admin/admins", json={"email": "ops@example.com", "name": "运维", "password": "Ops-pass-123"}, headers=H)
    assert r.status_code == 200
    aid = r.json()["id"]
    with TestClient(app.app) as c2:
        assert c2.post("/api/admin/auth/login", json={"email": "ops@example.com", "password": "Ops-pass-123"}).status_code == 200
        assert c2.get("/api/admin/me").json()["email"] == "ops@example.com"
        app.patch(f"/api/admin/admins/{aid}", json={"active": False}, headers=H)
        assert c2.get("/api/admin/me").status_code == 401  # 停用后会话立即失效


def test_login_rate_limited(app):
    codes = [app.post("/api/admin/auth/login", json={"email": "x@example.com", "password": "bad-pass-1"}).status_code for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def test_invalid_api_key(app):
    assert chat(app, {"Authorization": "Bearer nope"}).status_code == 401


def test_platform_key_billing_with_markup(app, upstream):
    admin_login(app)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    assert chat(app, h).status_code == 402  # 无余额
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    r = chat(app, h)
    assert r.status_code == 200, r.text
    assert upstream.calls[-1][2]["authorization"] == "Bearer sk-platform-1234"
    # gpt-4o: 10*2.5 + 5*10 = 75 微美元，加价 20% = 90；冻结额已全部结算退回
    d = app.get(f"/api/admin/tenants/{tid}").json()
    assert d["balance_usd"] == pytest.approx(1 - 0.00009) and d["reserved_usd"] == 0
    assert d["recent"][0]["charge_usd"] == pytest.approx(0.00009) and d["recent"][0]["key_source"] == "platform"
    assert d["models"][0]["cost_usd"] == pytest.approx(0.000075)


def test_tenant_markup_override(app):
    admin_login(app)
    tid, h = tenant(app, markup_pct=100)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    chat(app, h)
    assert app.get(f"/api/admin/tenants/{tid}").json()["recent"][0]["charge_usd"] == pytest.approx(0.00015)


def test_byok_overrides_platform_and_no_balance_needed(app, upstream):
    admin_login(app)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.put(f"/api/admin/tenants/{tid}/upstream", json={"provider": "openai", "api_key": "sk-tenant-5678"}, headers=H)
    r = chat(app, h)
    assert r.status_code == 200
    assert upstream.calls[-1][2]["authorization"] == "Bearer sk-tenant-5678"
    assert app.get(f"/api/admin/tenants/{tid}").json()["recent"][0]["key_source"] == "byok"


def test_upstream_keys_encrypted_and_masked(app):
    admin_login(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    from autollm_admin.db import UpstreamKey
    async def go():
        async with app.app.state.Session() as s:
            return (await s.scalars(select(UpstreamKey))).one()
    row = app.portal.call(go)
    assert "sk-platform" not in row.enc_key
    lst = app.get("/api/admin/upstreams").json()
    o = [x for x in lst if x["provider"] == "openai"][0]
    assert o["configured"] and o["masked"].endswith("1234") and "sk-platform" not in str(lst)


def test_settings_update_and_validation(app):
    admin_login(app)
    assert app.put("/api/admin/settings", json={"platform_markup_pct": -1}, headers=H).status_code == 422
    assert app.put("/api/admin/settings", json={"alert_webhook_url": "ftp://x"}, headers=H).status_code == 422
    r = app.put("/api/admin/settings", json={"platform_markup_pct": 50, "alert_low_balance_usd": 5}, headers=H).json()
    assert r["platform_markup_pct"] == 50 and r["alert_low_balance_usd"] == 5
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    chat(app, h)
    assert app.get(f"/api/admin/tenants/{tid}").json()["recent"][0]["charge_usd"] == pytest.approx(0.000112)


def test_model_price_override_and_disable(app):
    admin_login(app)
    assert app.patch("/api/admin/models/gpt-4o", json={"price_in": 5, "price_out": 20}, headers=H).status_code == 200
    m = [x for x in app.get("/api/models").json()["models"] if x["model"] == "gpt-4o"][0]
    assert m["price_in"] == 6 and m["price_out"] == 24  # 含 20% 加价
    app.patch("/api/admin/models/gpt-4o", json={"enabled": False}, headers=H)
    assert "gpt-4o" not in [x["model"] for x in app.get("/api/models").json()["models"]]


def test_admin_overview_and_tenant_list_have_names(app):
    admin_login(app)
    tid, h = tenant(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    app.post(f"/api/admin/tenants/{tid}/topups", json={"amount_usd": 1}, headers=H)
    chat(app, h)
    ov = app.get("/api/admin/overview").json()
    assert ov["totals"]["requests"] == 1 and ov["top_tenants"][0]["name"] == "Acme 科技"
    assert len(ov["series"]) == 30
    t = app.get("/api/admin/tenants").json()[0]
    assert t["name"] == "Acme 科技" and t["month_requests"] == 1
    assert app.get("/api/admin/monitoring").json()["providers"][0]["provider"]


def test_webhook_mock_idempotent(app):
    admin_login(app)
    tid, _ = tenant(app)
    with TestClient(app.app) as t:
        t.post("/api/auth/signup", json={"email": "a@b.com", "password": "Passw0rd!", "company": "C"})
        tp = t.post("/api/console/topups", json={"amount_usd": 5, "channel": "mock"}, headers=H).json()
        for _ in range(2):
            app.post("/billing/webhook/mock", json={"topup_id": tp["id"], "paid": True})
        assert t.get("/api/me").json()["tenant"]["balance_usd"] == 5


def test_unconfigured_channel_501(app):
    with TestClient(app.app) as t:
        t.post("/api/auth/signup", json={"email": "a@b.com", "password": "Passw0rd!", "company": "C"})
        assert t.post("/api/console/topups", json={"amount_usd": 5, "channel": "stripe"}, headers=H).status_code == 501
