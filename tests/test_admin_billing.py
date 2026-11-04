import pytest
from fastapi.testclient import TestClient
from autollm_admin.main import build
from autollm_admin.billing import Pricing
from autollm_gate.router import load_config

ADMIN = {"X-Admin-Token": "adm"}


@pytest.fixture
def app(monkeypatch, client_factory, master_key):
    monkeypatch.setenv("ADMIN_TOKEN", "adm")
    monkeypatch.setenv("ENABLE_MOCK_PAYMENT", "1")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("PLATFORM_MARKUP_PCT", "20")
    monkeypatch.setenv("BYOK_FEE_PER_REQUEST_USD", "0")
    monkeypatch.setenv("BYOK_FEE_PER_1K_TOKENS_USD", "0")
    return TestClient(build("sqlite://", master_key, client=client_factory()))


def tenant(app, **kw):
    t = app.post("/admin/api/tenants", json={"name": "acme", **kw}, headers=ADMIN).json()
    k = app.post(f"/admin/api/tenants/{t['id']}/keys", json={"name": "k"}, headers=ADMIN).json()["api_key"]
    return t["id"], {"Authorization": f"Bearer {k}"}


def chat(app, h, model="gpt-4o"):
    return app.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}]}, headers=h)


def test_admin_auth(app):
    assert app.get("/admin/api/tenants").status_code == 401
    assert app.get("/admin/api/tenants", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert app.get("/admin").status_code == 200


def test_invalid_api_key(app):
    assert chat(app, {"Authorization": "Bearer nope"}).status_code == 401


def test_platform_key_billing_with_markup(app, upstream):
    tid, h = tenant(app)
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    assert chat(app, h).status_code == 402  # 无余额
    app.post(f"/admin/api/tenants/{tid}/topups", json={"amount_usd": 1}, headers=ADMIN)
    r = chat(app, h)
    assert r.status_code == 200, r.text
    assert upstream.calls[-1][2]["authorization"] == "Bearer sk-platform-1234"
    # gpt-4o: 10*2.5 + 5*10 = 75 微美元，加价 20% = 90
    bal = app.get("/billing/balance", headers=h).json()["balance_usd"]
    assert bal == pytest.approx(1 - 0.00009)
    u = app.get("/admin/api/usage", headers=ADMIN).json()[0]
    assert u["key_source"] == "platform" and u["cost_usd"] == pytest.approx(0.000075) and u["charge_usd"] == pytest.approx(0.00009)


def test_tenant_markup_override(app):
    tid, h = tenant(app, markup_pct=100)
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    app.post(f"/admin/api/tenants/{tid}/topups", json={"amount_usd": 1}, headers=ADMIN)
    chat(app, h)
    assert app.get("/admin/api/usage", headers=ADMIN).json()[0]["charge_usd"] == pytest.approx(0.00015)


def test_byok_overrides_platform_and_no_balance_needed(app, upstream):
    tid, h = tenant(app)
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    app.put(f"/admin/api/tenants/{tid}/upstream", json={"provider": "openai", "api_key": "sk-tenant-5678"}, headers=ADMIN)
    r = chat(app, h)
    assert r.status_code == 200
    assert upstream.calls[-1][2]["authorization"] == "Bearer sk-tenant-5678"
    assert app.get("/admin/api/usage", headers=ADMIN).json()[0]["key_source"] == "byok"


def test_upstream_keys_encrypted(app):
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    from autollm_admin.db import UpstreamKey
    with app.app.state.Session() as s:
        row = s.query(UpstreamKey).one()
        assert "sk-platform" not in row.enc_key and row.hint == "…1234"
    lst = app.get("/admin/api/platform/upstream", headers=ADMIN).json()
    assert "api_key" not in lst[0] and "enc_key" not in lst[0]


def test_selfhosted_billing(app, upstream):
    tid, h = tenant(app)
    app.put("/admin/api/platform/upstream", json={"provider": "selfhosted", "api_key": "local-token"}, headers=ADMIN)
    app.post(f"/admin/api/tenants/{tid}/topups", json={"amount_usd": 1}, headers=ADMIN)
    r = chat(app, h, "auto")
    assert r.status_code == 200 and r.headers["x-router-provider"] == "selfhosted"
    u = app.get("/admin/api/usage", headers=ADMIN).json()[0]
    assert u["key_source"] == "selfhosted" and u["charge_usd"] == u["cost_usd"] > 0


def test_monthly_token_limit(app):
    tid, h = tenant(app, monthly_token_limit=15)
    app.put(f"/admin/api/tenants/{tid}/upstream", json={"provider": "openai", "api_key": "sk-tenant-5678"}, headers=ADMIN)
    assert chat(app, h).status_code == 200  # 用掉 15
    assert chat(app, h).status_code == 429


def test_revoke_and_disable(app):
    tid, h = tenant(app)
    app.put(f"/admin/api/tenants/{tid}/upstream", json={"provider": "openai", "api_key": "sk-tenant-5678"}, headers=ADMIN)
    app.patch(f"/admin/api/tenants/{tid}", json={"active": False}, headers=ADMIN)
    assert chat(app, h).status_code == 403
    app.patch(f"/admin/api/tenants/{tid}", json={"active": True}, headers=ADMIN)
    kid = app.get(f"/admin/api/tenants/{tid}/keys", headers=ADMIN).json()[0]["id"]
    app.delete(f"/admin/api/keys/{kid}", headers=ADMIN)
    assert chat(app, h).status_code == 401


def test_topup_flow_mock_and_unconfigured(app):
    tid, h = tenant(app)
    tp = app.post("/billing/topups", json={"amount_usd": 5, "channel": "mock"}, headers=h).json()
    assert tp["status"] == "pending" and tp["checkout"]["type"] == "mock"
    app.post("/billing/webhook/mock", json={"topup_id": tp["id"], "paid": True})
    app.post("/billing/webhook/mock", json={"topup_id": tp["id"], "paid": True})  # 幂等
    assert app.get("/billing/balance", headers=h).json()["balance_usd"] == 5
    assert app.post("/billing/topups", json={"amount_usd": 5, "channel": "stripe"}, headers=h).status_code == 501
    assert app.post("/billing/topups", json={"amount_usd": 5, "channel": "manual"}, headers=h).status_code == 400
    assert len(app.get("/billing/topups", headers=h).json()) == 2


def test_byok_service_fee():
    p = Pricing(load_config(), markup_pct=20, byok_fee_per_request=0.001, byok_fee_per_1k_tokens=0.01)
    assert p.charge_micro(999, "byok", None, tokens=2000) == 1000 + 20000
    assert p.charge_micro(100, "platform", None) == 120
    assert p.charge_micro(100, "selfhosted", None) == 100
    assert p.cost_micro("unknown-model", 1, 1) > 0


def test_streaming_usage_billed(app):
    tid, h = tenant(app)
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    app.post(f"/admin/api/tenants/{tid}/topups", json={"amount_usd": 1}, headers=ADMIN)
    with app.stream("POST", "/v1/chat/completions", json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]}, headers=h) as r:
        "".join(r.iter_text())
    u = app.get("/admin/api/usage", headers=ADMIN).json()[0]
    assert u["prompt_tokens"] == 10 and u["completion_tokens"] == 5


def test_markup_editable_in_admin(app):
    assert app.get("/admin/api/settings", headers=ADMIN).json()["platform_markup_pct"] == 20
    assert app.put("/admin/api/settings", json={"platform_markup_pct": 50}, headers=ADMIN).json()["platform_markup_pct"] == 50
    tid, h = tenant(app)
    app.put("/admin/api/platform/upstream", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=ADMIN)
    app.post(f"/admin/api/tenants/{tid}/topups", json={"amount_usd": 1}, headers=ADMIN)
    chat(app, h)
    assert app.get("/admin/api/usage", headers=ADMIN).json()[0]["charge_usd"] == pytest.approx(0.0001125, abs=1e-6)
    assert app.put("/admin/api/settings", json={"platform_markup_pct": -1}, headers=ADMIN).status_code == 422
    # 租户级覆盖可清空回全局
    assert app.patch(f"/admin/api/tenants/{tid}", json={"markup_pct": 10}, headers=ADMIN).json()["markup_pct"] == 10
