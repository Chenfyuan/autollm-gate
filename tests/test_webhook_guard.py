import asyncio
import socket

import httpx
import pytest

from test_v02_billing import H, admin_login, app, env  # noqa: F401  (复用 fixture)
from autollm_admin import webhook_guard as wg
from autollm_admin.webhook_guard import WebhookURLError, validate_webhook_url


def run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/x", "http://172.16.1.1/x",
    "http://192.168.1.1/x", "http://169.254.169.254/latest/meta-data", "http://0.0.0.0/x",
    "http://224.0.0.1/x", "http://240.0.0.1/x", "http://100.64.0.1/x",
    "http://[::1]/x", "http://[fe80::1]/x", "http://[fc00::1]/x", "http://[ff02::1]/x",
    "http://[::ffff:127.0.0.1]/x", "http://[::]/x",
])
def test_rejects_internal(url):
    with pytest.raises(WebhookURLError):
        run(validate_webhook_url(url))


@pytest.mark.parametrize("url", ["ftp://93.184.216.34/x", "file:///etc/passwd", "http://u:p@93.184.216.34/", "notaurl"])
def test_rejects_bad_scheme(url):
    with pytest.raises(WebhookURLError):
        run(validate_webhook_url(url))


def test_allows_public_ip_and_http_outside_prod(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    run(validate_webhook_url("http://93.184.216.34/hook"))
    run(validate_webhook_url("https://[2606:2800:220:1::1]/hook"))


def test_production_requires_https(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(WebhookURLError, match="https"):
        run(validate_webhook_url("http://93.184.216.34/hook"))
    run(validate_webhook_url("https://93.184.216.34/hook"))


def test_hostname_resolving_to_private_rejected(monkeypatch):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    monkeypatch.setattr(wg.socket, "getaddrinfo", fake)
    with pytest.raises(WebhookURLError):
        run(validate_webhook_url("https://evil.example.com/hook"))


def test_unresolvable_rejected(monkeypatch):
    def fake(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(wg.socket, "getaddrinfo", fake)
    with pytest.raises(WebhookURLError):
        run(validate_webhook_url("https://nope.invalid/hook"))


def test_save_time_rejects_private(app):
    admin_login(app)
    r = app.put("/api/admin/settings", json={"alert_webhook_url": "http://169.254.169.254/x"}, headers=H)
    assert r.status_code == 422
    assert app.put("/api/admin/settings", json={"alert_webhook_url": "http://93.184.216.34/x"}, headers=H).status_code == 200


def test_send_time_blocks_after_dns_change(app, monkeypatch):
    """保存时解析到公网，发送前 DNS 变为内网地址（rebinding），仍要拦截。"""
    calls = []
    app.app.state.alerter.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(200))[1]))
    target = {"ip": "93.184.216.34"}
    monkeypatch.setattr(wg.socket, "getaddrinfo", lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (target["ip"], p))])
    admin_login(app)
    assert app.put("/api/admin/settings", json={"alert_webhook_url": "http://hook.example.com/x"}, headers=H).status_code == 200
    target["ip"] = "127.0.0.1"
    ev = run(app.app.state.alerter.fire("test", "t1", "测试", "msg", force=True))
    assert calls == [] and not ev.delivered and "已拦截" in ev.delivery_error
