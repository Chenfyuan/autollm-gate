import pytest
from autollm_gate.router import classify, load_config, select, parse_strategy
from autollm_gate.session import extract_session_id, SessionStore

CFG = load_config()
ALL = {"openai", "anthropic", "gemini", "deepseek", "selfhosted"}


def B(text, model="auto", **kw):
    return {"model": model, "messages": [{"role": "user", "content": text}], **kw}


def test_classify():
    assert classify(B("你好")) == "chat"
    assert classify(B("这段代码报错了 def f(): pass")) == "coding"
    assert classify(B("请一步一步证明这个定理")) == "reasoning"
    assert classify(B("x", tools=[{"type": "function", "function": {"name": "a"}}])) == "coding"
    assert classify(B("字" * 100000)) == "long_context"


def test_strategy_parse():
    assert parse_strategy("auto", CFG) == "cost_optimized"
    assert parse_strategy("auto:quality_first", CFG) == "quality_first"
    assert parse_strategy("gpt-4o", CFG) is None
    with pytest.raises(ValueError):
        parse_strategy("auto:nope", CFG)


def test_strategies_differ():
    cost = select(B("你好"), CFG, ALL)
    qual = select(B("你好", "auto:quality_first"), CFG, ALL)
    fast = select(B("你好", "auto:latency_critical"), CFG, ALL)
    m = CFG["models"]
    assert m[cost.model]["price_out"] <= m[qual.model]["price_out"]
    assert m[qual.model]["quality"] >= 8.5
    assert m[fast.model]["speed"] >= 9
    assert "strategy=cost_optimized" in cost.reason


def test_coding_quality_prefers_coding_model():
    d = select(B("帮我重构这段代码 ```python\nx=1```", "auto:quality_first"), CFG, ALL)
    assert d.task == "coding" and d.model == "claude-sonnet-4-5"


def test_available_filter_and_explicit():
    d = select(B("hi"), CFG, {"deepseek"})
    assert all(CFG["models"][c]["provider"] == "deepseek" for c in d.candidates)
    e = select(B("hi", "gpt-4o"), CFG, ALL)
    assert e.model == "gpt-4o" and e.strategy == "explicit" and len(e.candidates) > 1
    with pytest.raises(LookupError):
        select(B("hi"), CFG, set())


def test_long_context_filters_small_models():
    d = select(B("字" * 300000), CFG, ALL)
    assert all(CFG["models"][c]["context"] > 100000 for c in d.candidates)


def test_session_id_sources():
    assert extract_session_id({"X-Session-Id": "abc"}, {}) == "abc"
    assert extract_session_id({}, {"metadata": {"user_id": "user_x_account_y_session_1234"}}) == "cc:1234"
    assert extract_session_id({"session_id": "codex1"}, {}) == "codex1"
    assert extract_session_id({}, {"prompt_cache_key": "k"}) == "prompt_cache_key:k"
    b = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}]}
    assert extract_session_id({}, b).startswith("fp:")
    assert extract_session_id({}, {"messages": [{"role": "user", "content": "q"}]}) is None


def test_session_store_ttl():
    import asyncio
    from autollm_gate.state import MemoryState
    s = SessionStore(MemoryState(), ttl=1)
    async def go():
        await s.set("a", "m")
        assert await s.get("a") == "m"
        s.state._kv = {k: (v, 1.0) for k, (v, _) in s.state._kv.items()}  # 人为过期
        assert await s.get("a") is None
    asyncio.run(go())
