import json, os
import httpx, pytest
from cryptography.fernet import Fernet

os.environ.setdefault("AUTOLLM_ADMIN_NO_AUTOBUILD", "1")


class MockUpstream:
    """按 URL 模拟各家上游；fail 集合中的 provider 返回 500。"""
    def __init__(self):
        self.fail, self.calls = set(), []

    def provider_of(self, url):
        h = url.host
        return {"api.openai.com": "openai", "api.anthropic.com": "anthropic", "api.deepseek.com": "deepseek",
                "generativelanguage.googleapis.com": "gemini"}.get(h, "selfhosted")

    def __call__(self, req: httpx.Request):
        p = self.provider_of(req.url)
        body = json.loads(req.content or b"{}")
        self.calls.append((p, body, dict(req.headers)))
        if p in self.fail:
            return httpx.Response(500, json={"error": "boom"})
        stream = body.get("stream") or "streamGenerateContent" in str(req.url)
        if p == "anthropic":
            if stream:
                evs = [{"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
                       {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "你好"}},
                       {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "get_weather", "input": {}}},
                       {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"city\":\"SG\"}"}},
                       {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}}]
                return httpx.Response(200, text="".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in evs))
            content = [{"type": "text", "text": "hi from claude"}]
            if body.get("tools"):
                content.append({"type": "tool_use", "id": "tu1", "name": body["tools"][0]["name"], "input": {"city": "SG"}})
            return httpx.Response(200, json={"id": "msg1", "content": content, "stop_reason": "tool_use" if body.get("tools") else "end_turn",
                                             "usage": {"input_tokens": 10, "output_tokens": 5}})
        if p == "gemini":
            d = {"candidates": [{"content": {"parts": [{"text": "hi from gemini"}]}, "finishReason": "STOP"}],
                 "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15}}
            if stream:
                return httpx.Response(200, text=f"data: {json.dumps(d)}\n\n")
            return httpx.Response(200, json=d)
        # OpenAI 兼容（openai / deepseek / selfhosted）
        if stream:
            cs = [{"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}]
            return httpx.Response(200, text="".join(f"data: {json.dumps(c)}\n\n" for c in cs) + "data: [DONE]\n\n")
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "model": body["model"],
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": f"hi from {p}"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


@pytest.fixture
def upstream():
    return MockUpstream()


@pytest.fixture
def client_factory(upstream):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream))


@pytest.fixture
def master_key():
    return Fernet.generate_key().decode()
