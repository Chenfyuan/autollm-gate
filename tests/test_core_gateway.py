import json
import pytest
from fastapi.testclient import TestClient
from autollm_gate.gateway import create_app
from autollm_gate.anthropic_compat import messages_to_openai
from autollm_gate.providers import openai_to_anthropic, openai_to_gemini


@pytest.fixture
def app(monkeypatch, client_factory):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "SELFHOSTED_API_KEY"):
        monkeypatch.setenv(k, "test-" + k)
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    return TestClient(create_app(client=client_factory()))


def chat(c, model="auto", text="你好", **kw):
    return c.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": text}], **kw}, headers=kw.pop("headers", {}) if False else {})


def test_models(app):
    ids = [m["id"] for m in app.get("/v1/models").json()["data"]]
    assert "auto" in ids and "auto:balanced" in ids and "gpt-4o" in ids and "qwen3-32b" in ids


def test_auto_chat_headers(app):
    r = chat(app)
    assert r.status_code == 200, r.text
    assert r.headers["x-router-model"] and r.headers["x-router-strategy"] == "cost_optimized"
    assert "task=chat" in r.headers["x-router-reason"]
    assert r.json()["choices"][0]["message"]["content"].startswith("hi from")


def test_explicit_model_each_provider(app):
    for m, expect in [("gpt-4o", "openai"), ("deepseek-chat", "deepseek"), ("claude-haiku-4-5", "claude"), ("gemini-2.5-flash", "gemini"), ("qwen3-32b", "selfhosted")]:
        r = chat(app, m)
        assert r.status_code == 200 and expect in r.json()["choices"][0]["message"]["content"], (m, r.text)
        assert r.headers["x-router-model"] == m


def test_fallback(app, upstream):
    upstream.fail = {"openai"}
    r = chat(app, "gpt-4o")
    assert r.status_code == 200
    assert r.headers["x-router-provider"] != "openai" and int(r.headers["x-router-attempts"]) >= 2
    assert "fallback" in r.headers["x-router-reason"]


def test_all_fail(app, upstream):
    upstream.fail = {"openai", "anthropic", "gemini", "deepseek", "selfhosted"}
    r = chat(app)
    assert r.status_code == 502


def test_bad_strategy(app):
    assert chat(app, "auto:xxx").status_code == 400


def test_stream_openai(app):
    with app.stream("POST", "/v1/chat/completions", json={"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
        text = "".join(r.iter_text())
    assert '"hi"' in text and text.strip().endswith("[DONE]")


def test_stream_anthropic_upstream_to_openai(app):
    with app.stream("POST", "/v1/chat/completions", json={"model": "claude-sonnet-4-5", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
        text = "".join(r.iter_text())
    assert "你好" in text and "get_weather" in text and "tool_calls" in text


def test_session_sticky(app, upstream):
    h = {"X-Session-Id": "s1"}
    r1 = app.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "你好"}]}, headers=h)
    first = r1.headers["x-router-model"]
    # 第二轮内容变成代码类，若无粘性会换模型；粘性下保持不变
    r2 = app.post("/v1/chat/completions", json={"model": "auto:quality_first", "messages": [{"role": "user", "content": "写代码 ```x```"}]}, headers=h)
    assert r2.headers["x-router-model"] == first and "session-sticky" in r2.headers["x-router-reason"]


def test_anthropic_messages_endpoint_with_tools(app):
    body = {"model": "claude-sonnet-4-5", "max_tokens": 100, "system": "be nice",
            "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
            "messages": [{"role": "user", "content": "天气？"}]}
    r = app.post("/v1/messages", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "message" and d["stop_reason"] == "tool_use"
    assert any(b["type"] == "tool_use" and b["input"] == {"city": "SG"} for b in d["content"])


def test_anthropic_messages_stream(app):
    body = {"model": "claude-sonnet-4-5", "max_tokens": 100, "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    with app.stream("POST", "/v1/messages", json=body) as r:
        text = "".join(r.iter_text())
    for ev in ("message_start", "content_block_start", "text_delta", "input_json_delta", "message_delta", "message_stop"):
        assert ev in text
    assert '"stop_reason": "tool_use"' in text


def test_anthropic_messages_routed_to_openai(app):
    r = app.post("/v1/messages", json={"model": "gpt-4o", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]})
    assert r.json()["content"][0]["text"] == "hi from openai"


def test_claude_code_metadata_stickiness(app):
    meta = {"user_id": "user_a_account_b_session_xyz"}
    r1 = app.post("/v1/messages", json={"model": "auto", "max_tokens": 10, "metadata": meta, "messages": [{"role": "user", "content": "hi"}]})
    r2 = app.post("/v1/messages", json={"model": "auto:quality_first", "max_tokens": 10, "metadata": meta, "messages": [{"role": "user", "content": "hi"}]})
    assert r1.headers["x-router-model"] == r2.headers["x-router-model"]


def test_count_tokens(app):
    assert app.post("/v1/messages/count_tokens", json={"messages": [{"role": "user", "content": "abcdef"}]}).json()["input_tokens"] >= 1


def test_router_api_key(monkeypatch, client_factory):
    monkeypatch.setenv("ROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    c = TestClient(create_app(client=client_factory()))
    assert c.get("/v1/models").status_code == 401
    assert c.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_conversions_roundtrip():
    o = messages_to_openai({"system": "s", "messages": [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "42"}]}]})
    assert o["messages"][0]["role"] == "system" and o["messages"][2]["tool_calls"][0]["id"] == "t1"
    assert o["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": "42"}
    a = openai_to_anthropic(o, "claude")
    assert a["system"] == "s" and a["messages"][2]["content"][0]["type"] == "tool_result"
    g = openai_to_gemini(o)
    assert g["contents"][2]["parts"][0]["functionResponse"]["name"] == "f"
