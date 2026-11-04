"""v0.3：Key 级策略、请求日志检索/导出、审计日志、embeddings、跨副本熔断共享、Webhook 防 DNS rebinding、核心插件加载。"""
import asyncio, sys, types
import httpx, pytest
from test_admin_billing import H, admin_login, app, chat, env, make_app  # noqa: F401


def setup(app, **policy):
    admin_login(app)
    app.put("/api/admin/upstreams", json={"provider": "openai", "api_key": "sk-platform-1234"}, headers=H)
    t = app.post("/api/admin/tenants", json={"name": "策略测试"}, headers=H).json()
    app.post(f"/api/admin/tenants/{t['id']}/topups", json={"amount_usd": 5}, headers=H)
    r = app.post(f"/api/admin/tenants/{t['id']}/keys", json={"name": "k", **policy}, headers=H)
    assert r.status_code == 200, r.text
    k = r.json()
    return t["id"], k, {"Authorization": f"Bearer {k['api_key']}"}


def test_model_allowlist(app):
    _, k, h = setup(app, allowed_models=["gpt-4o-mini", "deepseek*"])
    assert k["allowed_models"] == ["gpt-4o-mini", "deepseek*"]
    assert chat(app, h, "gpt-4o").status_code == 403
    r = chat(app, h, "gpt-4o-mini")
    assert r.status_code == 200 and r.headers["x-router-model"] == "gpt-4o-mini"


def test_auto_routing_respects_allowlist(app):
    _, _, h = setup(app, allowed_models=["gpt-4o"])
    r = chat(app, h, "auto")
    assert r.status_code == 200 and r.headers["x-router-model"] == "gpt-4o"


def test_key_expiry(app):
    _, k, h = setup(app, expires_at="2020-01-01T00:00:00Z")
    r = chat(app, h)
    assert r.status_code == 401 and "过期" in r.text
    app.patch(f"/api/admin/keys/{k['id']}", json={"clear_expiry": True}, headers=H)
    assert chat(app, h).status_code == 200


def test_ip_allowlist(app):
    _, k, h = setup(app, ip_allowlist=["203.0.113.0/24"])
    assert chat(app, h).status_code == 403  # TestClient 来源为 testclient，不在白名单
    assert app.post(f"/api/admin/tenants/x/keys", json={"ip_allowlist": ["not-an-ip"]}, headers=H).status_code == 422


def test_ip_allowlist_behind_proxy(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    _, _, h = setup(app, ip_allowlist=["203.0.113.0/24"])
    assert chat(app, h | {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}).status_code == 200
    assert chat(app, h | {"X-Forwarded-For": "198.51.100.1"}).status_code == 403


def test_spend_limit(app):
    _, k, h = setup(app, spend_limit_usd=0.000001)
    assert chat(app, h).status_code == 200  # 第一次扣费后达到上限
    r = chat(app, h)
    assert r.status_code == 402 and "消费上限" in r.text
    app.patch(f"/api/admin/keys/{k['id']}", json={"clear_spend_limit": True}, headers=H)
    assert chat(app, h).status_code == 200


def test_logs_search_and_csv(app):
    tid, _, h = setup(app)
    for m in ("gpt-4o", "gpt-4o-mini", "gpt-4o"):
        assert chat(app, h, m).status_code == 200
    r = app.get("/api/admin/logs", params={"tenant_id": tid, "model": "mini"}).json()
    assert r["total"] == 1 and r["items"][0]["model"] == "gpt-4o-mini" and r["items"][0]["tenant_name"] == "策略测试"
    assert app.get("/api/admin/logs", params={"tenant_id": tid}).json()["total"] == 3
    assert app.get("/api/admin/logs", params={"tenant_id": tid, "start": "2999-01-01"}).json()["total"] == 0
    csv = app.get("/api/admin/logs", params={"tenant_id": tid, "format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.lstrip("\ufeff").splitlines()[0].startswith("id,created_at") and len(csv.text.splitlines()) == 4


def test_audit_log(app):
    tid, k, _ = setup(app)
    app.patch(f"/api/admin/tenants/{tid}", json={"rpm_limit": 100}, headers=H)
    app.patch(f"/api/admin/keys/{k['id']}", json={"allowed_models": ["gpt-4o"]}, headers=H)
    items = app.get("/api/admin/audit").json()["items"]
    acts = [i["action"] for i in items]
    assert "key.create" in acts and "key.update" in acts and "patch tenants" in acts and "post tenants" in acts
    assert all(i["actor"] == "root@example.com" for i in items)
    upd = next(i for i in items if i["action"] == "key.update")
    assert upd["detail"]["allowed_models"] == ["gpt-4o"]
    assert app.get("/api/admin/audit", params={"action": "key."}).json()["total"] == 2


def test_embeddings(app, upstream):
    _, _, h = setup(app)
    r = app.post("/v1/embeddings", json={"model": "text-embedding-3-small", "input": ["a", "b"]}, headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 2 and r.headers["x-router-provider"] == "openai"
    assert app.post("/v1/embeddings", json={"model": "x"}, headers=h).status_code == 400


def test_shared_breaker_skips_provider(app):
    _, _, h = setup(app)
    gw = app.app.state.gateway
    app.portal.call(gw._share_open, "openai", 30)
    r = chat(app, h, "gpt-4o")
    assert r.status_code in (502, 503) and "shared" in r.text


def test_webhook_pinned_target():
    from autollm_admin.webhook_guard import pinned_target
    url, hdr, ext = pinned_target("https://hooks.example.com:8443/x?a=1", "93.184.216.34")
    assert url == "https://93.184.216.34:8443/x?a=1" and hdr["Host"] == "hooks.example.com:8443" and ext == {"sni_hostname": "hooks.example.com"}
    url, _, ext = pinned_target("http://hooks.example.com/x", "2606:2800::1")
    assert url == "http://[2606:2800::1]/x" and ext == {}


def test_webhook_connects_to_checked_ip(monkeypatch):
    """DNS rebinding：校验时解析到公网 IP，真正发送时也必须连这个 IP，而不是再次解析域名。"""
    from autollm_admin import webhook_guard as wg
    from autollm_admin.alerts import Alerter
    monkeypatch.setattr(wg, "_resolve", lambda h, p: ["93.184.216.34"])
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers.get("host"), req.extensions.get("sni_hostname")))
        return httpx.Response(200)
    a = Alerter.__new__(Alerter)
    a.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a.state = types.SimpleNamespace(set=lambda *a, **k: asyncio.sleep(0, True))
    a.cfg = lambda: {"alert_cooldown_minutes": 1, "alert_webhook_url": "https://hooks.example.com/hook", "alert_webhook_format": "generic"}

    class S:
        async def __aenter__(self): return self
        async def __aexit__(self, *e): pass
        def add(self, x): self.x = x
        async def commit(self): pass
    a.Session = S
    asyncio.run(a.fire("test", "k", "t", "m", force=True))
    assert seen == [("https://93.184.216.34/hook", "hooks.example.com", "hooks.example.com")]


def test_core_plugin_env(monkeypatch):
    from autollm_gate import plugins
    from autollm_gate.router import Decision
    mod = types.ModuleType("fake_core")

    class Core:
        name = "fake"
        @staticmethod
        def select(body, cfg, avail):
            return Decision("gpt-4o-mini", ["gpt-4o-mini"], "plugin", "-", "from plugin")
    mod.plugin = Core()
    monkeypatch.setitem(sys.modules, "fake_core", mod)
    monkeypatch.setenv("AUTOLLM_CORE_PLUGIN", "fake_core:plugin")
    plugins.reset()
    try:
        from autollm_gate.gateway import create_app
        from fastapi.testclient import TestClient
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        with TestClient(create_app(client=httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "x"}}], "usage": {}}))))) as c:
            assert c.get("/healthz").json()["core"] == "fake"
            r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
            assert r.status_code == 200 and r.headers["x-router-strategy"] == "plugin"
    finally:
        plugins.reset()


def test_core_plugin_bad_spec_falls_back(monkeypatch):
    from autollm_gate import plugins
    monkeypatch.setenv("AUTOLLM_CORE_PLUGIN", "no_such_module_xyz:plugin")
    plugins.reset()
    assert plugins.load_core().name == "default"
    plugins.reset()


def test_console_key_policy_and_logs(app):
    tid, _, h = setup(app)
    # 租户自助：注册账号走控制台
    r = app.post("/api/auth/signup", json={"email": "dev@example.com", "password": "Passw0rd-xyz", "name": "开发", "company": "示例公司"}, headers=H)
    assert r.status_code == 200, r.text
    k = app.post("/api/console/keys", json={"name": "ci", "allowed_models": ["gpt-4o-mini"], "expires_in_days": 30, "spend_limit_usd": 2}, headers=H).json()
    assert k["allowed_models"] == ["gpt-4o-mini"] and k["expires_at"] and k["spend_limit_usd"] == 2
    p = app.patch(f"/api/console/keys/{k['id']}", json={"ip_allowlist": ["198.51.100.0/24"]}, headers=H).json()
    assert p["ip_allowlist"] == ["198.51.100.0/24"]
    assert app.get("/api/console/logs").json()["total"] == 0
