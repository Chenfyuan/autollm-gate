"""v0.2 内核：Responses API、429/5xx/超时降级、熔断器、指标与就绪检查。"""
import json
import pytest
from fastapi.testclient import TestClient
from autollm_gate.gateway import create_app
from autollm_gate.breaker import CircuitBreaker
from autollm_gate.responses_compat import responses_to_chat


@pytest.fixture
def app(monkeypatch, client_factory):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "SELFHOSTED_API_KEY"):
        monkeypatch.setenv(k, "test-" + k)
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with TestClient(create_app(client=client_factory())) as c:
        yield c


def chat(c, model="gpt-4o"):
    return c.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}]})


@pytest.mark.parametrize("mode", ["429", "500", "503", "timeout"])
def test_failover_on_upstream_error(app, upstream, mode):
    upstream.modes["openai"] = mode
    r = chat(app)
    assert r.status_code == 200, r.text
    assert r.headers["x-router-provider"] != "openai"
    assert int(r.headers["x-router-attempts"]) == 2
    assert "fallback#1" in r.headers["x-router-reason"]


@pytest.mark.parametrize("mode", ["429", "503", "timeout"])
def test_failover_streaming_before_first_chunk(app, upstream, mode):
    upstream.modes["openai"] = mode
    with app.stream("POST", "/v1/chat/completions", json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
        assert r.status_code == 200
        assert r.headers["x-router-provider"] != "openai"
        assert "[DONE]" in "".join(r.iter_text())


def test_bad_request_400_not_failover_breaker(app, upstream):
    upstream.modes["openai"] = "400"
    r = chat(app)
    assert r.status_code == 502
    assert app.app.state.gateway.breakers.get("openai").state == "closed"


def test_circuit_breaker_opens_and_skips(app, upstream):
    gw = app.app.state.gateway
    upstream.modes["openai"] = "503"
    for _ in range(gw.breakers.get("openai").threshold):
        chat(app)
    assert gw.breakers.get("openai").state == "open"
    n = len([c for c in upstream.calls if c[0] == "openai"])
    r = chat(app)
    assert r.status_code == 200 and "circuit open" in r.headers["x-router-reason"]
    assert len([c for c in upstream.calls if c[0] == "openai"]) == n  # 熔断期间不再打到 openai


def test_breaker_half_open_recovery():
    b = CircuitBreaker(threshold=2, cooldown=0)
    b.failure(); b.failure()
    assert b.state == "open"
    assert b.allow() and b.state == "half_open"
    assert not b.allow()  # 半开只放行一个探测
    b.success()
    assert b.state == "closed" and b.allow()
    b2 = CircuitBreaker(threshold=1, cooldown=0)
    b2.failure(); b2.allow(); b2.failure()
    assert b2.state == "open"


def test_all_breakers_open_returns_503(app, upstream):
    gw = app.app.state.gateway
    for p in ("openai", "anthropic", "gemini", "deepseek", "selfhosted"):
        br = gw.breakers.get(p); br.cooldown = 3600
        for _ in range(br.threshold):
            br.failure()
    r = chat(app)
    assert r.status_code == 503 and "熔断" in r.text


def test_responses_non_stream(app):
    r = app.post("/v1/responses", json={"model": "gpt-4o", "instructions": "be brief", "input": "hi"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["object"] == "response" and d["status"] == "completed"
    assert d["output"][0]["content"][0]["text"] == "hi from openai"
    assert d["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_responses_tool_call_non_stream(app):
    r = app.post("/v1/responses", json={"model": "claude-sonnet-4-5", "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "天气"}]}],
                                        "tools": [{"type": "function", "name": "get_weather", "parameters": {"type": "object"}}]})
    out = r.json()["output"]
    fc = [o for o in out if o["type"] == "function_call"][0]
    assert fc["name"] == "get_weather" and json.loads(fc["arguments"]) == {"city": "SG"}


def test_responses_stream(app):
    with app.stream("POST", "/v1/responses", json={"model": "claude-sonnet-4-5", "stream": True, "input": "hi"}) as r:
        text = "".join(r.iter_text())
    for ev in ("response.created", "response.output_item.added", "response.output_text.delta", "response.output_text.done",
               "response.function_call_arguments.delta", "response.output_item.done", "response.completed"):
        assert f"event: {ev}" in text, ev
    last = [l for l in text.splitlines() if l.startswith("data:")][-1]
    done = json.loads(last[5:])
    assert done["response"]["usage"]["output_tokens"] == 5
    assert any(o["type"] == "function_call" and o["arguments"] == '{"city":"SG"}' for o in done["response"]["output"])


def test_responses_input_conversion():
    b = responses_to_chat({"model": "auto", "instructions": "sys", "max_output_tokens": 50, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "q"}]},
        {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "42"}]})
    assert b["messages"][0] == {"role": "system", "content": "sys"} and b["max_tokens"] == 50
    assert b["messages"][2]["tool_calls"][0]["id"] == "c1" and b["messages"][3]["role"] == "tool"


def test_metrics_and_health(app, upstream):
    chat(app)
    m = app.get("/metrics").text
    assert "autollm_upstream_requests_total" in m and 'provider="openai"' in m
    assert app.get("/healthz").json() == {"ok": True}
    r = app.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["state"] is True
