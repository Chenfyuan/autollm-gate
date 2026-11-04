"""上游适配器。内部统一使用 OpenAI Chat Completions 格式。"""
from __future__ import annotations
import json, os, time, uuid
from typing import AsyncIterator
import httpx

_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "selfhosted": "http://localhost:8000/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
# 每家上游都可用 <PROVIDER>_BASE_URL 覆盖（企业代理 / 自建中转 / 测试假上游）
BASE_URLS = {p: os.getenv(f"{p.upper()}_BASE_URL", u) for p, u in _DEFAULT_BASE_URLS.items()}


class UpstreamError(Exception):
    def __init__(self, provider: str, status: int, detail: str):
        super().__init__(f"{provider} {status}: {detail[:300]}")
        self.provider, self.status, self.detail = provider, status, detail

    @property
    def retryable(self) -> bool:
        return self.status in (0, 408, 409, 429) or self.status >= 500 or self.status in (401, 403, 404)


async def _sse_lines(resp: httpx.Response) -> AsyncIterator[str]:
    async for line in resp.aiter_lines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                yield data


def _chunk(model, delta, finish=None, usage=None, cid=None):
    c = {"id": cid or "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion.chunk", "created": int(time.time()),
         "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        c["usage"] = usage
    return c


class Provider:
    name = ""

    def __init__(self, client: httpx.AsyncClient, base_url: str | None = None):
        self.client, self.base = client, (base_url or BASE_URLS[self.name]).rstrip("/")

    async def _post(self, url, headers, payload, stream=False):
        try:
            req = self.client.build_request("POST", url, headers=headers, json=payload)
            resp = await self.client.send(req, stream=stream)
        except httpx.HTTPError as e:
            raise UpstreamError(self.name, 0, str(e))
        if resp.status_code >= 400:
            body = (await resp.aread()).decode(errors="replace")
            await resp.aclose()
            raise UpstreamError(self.name, resp.status_code, body)
        return resp


class OpenAICompatible(Provider):
    name = "openai"

    async def complete(self, model, body, key):
        p = {**body, "model": model, "stream": False}
        r = await self._post(f"{self.base}/chat/completions", {"Authorization": f"Bearer {key}"}, p)
        return r.json()

    async def embeddings(self, model, body, key):
        r = await self._post(f"{self.base}/embeddings", {"Authorization": f"Bearer {key}"}, {**body, "model": model})
        return r.json()

    async def stream(self, model, body, key):
        p = {**body, "model": model, "stream": True, "stream_options": {"include_usage": True}}
        r = await self._post(f"{self.base}/chat/completions", {"Authorization": f"Bearer {key}"}, p, stream=True)
        try:
            async for d in _sse_lines(r):
                yield json.loads(d)
        finally:
            await r.aclose()


class DeepSeek(OpenAICompatible):
    name = "deepseek"


class SelfHosted(OpenAICompatible):
    """平台自部署的开源权重模型（vLLM / Ollama / SGLang 等 OpenAI 兼容端点）。"""
    name = "selfhosted"


# ---------------- Anthropic ----------------
def openai_to_anthropic(body: dict, model: str) -> dict:
    system, msgs = [], []
    for m in body.get("messages", []):
        role, c = m["role"], m.get("content")
        if role in ("system", "developer"):
            system.append(c if isinstance(c, str) else "".join(p.get("text", "") for p in c))
        elif role == "tool":
            msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                                      "content": c if isinstance(c, str) else json.dumps(c)}]})
        elif role == "assistant" and m.get("tool_calls"):
            blocks = [{"type": "text", "text": c}] if c else []
            for tc in m["tool_calls"]:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                               "input": json.loads(tc["function"].get("arguments") or "{}")})
            msgs.append({"role": "assistant", "content": blocks})
        else:
            if isinstance(c, list):
                c = [{"type": "text", "text": p["text"]} if p.get("type") == "text" else p for p in c]
            msgs.append({"role": role, "content": c})
    # 合并相邻同角色（Anthropic 要求交替）
    merged = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            a, b = merged[-1]["content"], m["content"]
            norm = lambda x: x if isinstance(x, list) else [{"type": "text", "text": x}]
            merged[-1]["content"] = norm(a) + norm(b)
        else:
            merged.append(m)
    out = {"model": model, "messages": merged, "max_tokens": body.get("max_tokens") or body.get("max_completion_tokens") or 4096}
    if system:
        out["system"] = "\n".join(system)
    for k in ("temperature", "top_p"):
        if k in body:
            out[k] = body[k]
    if body.get("stop"):
        out["stop_sequences"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
    if body.get("tools"):
        out["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                         "input_schema": t["function"].get("parameters", {"type": "object"})} for t in body["tools"]]
    return out


_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}


class Anthropic(Provider):
    name = "anthropic"

    def _h(self, key):
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}

    async def complete(self, model, body, key):
        r = await self._post(f"{self.base}/messages", self._h(key), openai_to_anthropic(body, model))
        d = r.json()
        text = "".join(b.get("text", "") for b in d.get("content", []) if b["type"] == "text")
        tcs = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
               for b in d.get("content", []) if b["type"] == "tool_use"]
        msg = {"role": "assistant", "content": text or None}
        if tcs:
            msg["tool_calls"] = tcs
        u = d.get("usage", {})
        return {"id": d.get("id"), "object": "chat.completion", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": msg, "finish_reason": _STOP.get(d.get("stop_reason"), "stop")}],
                "usage": {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0),
                          "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0)}}

    async def stream(self, model, body, key):
        p = {**openai_to_anthropic(body, model), "stream": True}
        r = await self._post(f"{self.base}/messages", self._h(key), p, stream=True)
        pin = pout = 0
        tool_idx = {}
        try:
            async for d in _sse_lines(r):
                ev = json.loads(d)
                t = ev.get("type")
                if t == "message_start":
                    pin = ev["message"].get("usage", {}).get("input_tokens", 0)
                elif t == "content_block_start" and ev["content_block"]["type"] == "tool_use":
                    i = tool_idx[ev["index"]] = len(tool_idx)
                    b = ev["content_block"]
                    yield _chunk(model, {"tool_calls": [{"index": i, "id": b["id"], "type": "function",
                                                         "function": {"name": b["name"], "arguments": ""}}]})
                elif t == "content_block_delta":
                    dl = ev["delta"]
                    if dl["type"] == "text_delta":
                        yield _chunk(model, {"content": dl["text"]})
                    elif dl["type"] == "input_json_delta":
                        yield _chunk(model, {"tool_calls": [{"index": tool_idx.get(ev["index"], 0),
                                                             "function": {"arguments": dl["partial_json"]}}]})
                elif t == "message_delta":
                    pout = ev.get("usage", {}).get("output_tokens", pout)
                    yield _chunk(model, {}, _STOP.get(ev["delta"].get("stop_reason"), "stop"),
                                 {"prompt_tokens": pin, "completion_tokens": pout, "total_tokens": pin + pout})
        finally:
            await r.aclose()


# ---------------- Gemini ----------------
def openai_to_gemini(body: dict) -> dict:
    contents, system = [], []
    names = {}
    for m in body.get("messages", []):
        role, c = m["role"], m.get("content")
        text = c if isinstance(c, str) else "".join(p.get("text", "") for p in (c or []) if isinstance(p, dict))
        if role in ("system", "developer"):
            system.append(text)
        elif role == "tool":
            contents.append({"role": "user", "parts": [{"functionResponse": {"name": names.get(m["tool_call_id"], "tool"),
                                                                            "response": {"content": text}}}]})
        elif role == "assistant":
            parts = [{"text": text}] if text else []
            for tc in m.get("tool_calls") or []:
                names[tc["id"]] = tc["function"]["name"]
                parts.append({"functionCall": {"name": tc["function"]["name"], "args": json.loads(tc["function"].get("arguments") or "{}")}})
            contents.append({"role": "model", "parts": parts})
        else:
            contents.append({"role": "user", "parts": [{"text": text}]})
    out = {"contents": contents, "generationConfig": {}}
    if system:
        out["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
    if "temperature" in body:
        out["generationConfig"]["temperature"] = body["temperature"]
    if body.get("max_tokens"):
        out["generationConfig"]["maxOutputTokens"] = body["max_tokens"]
    if body.get("tools"):
        out["tools"] = [{"functionDeclarations": [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                                                   "parameters": t["function"].get("parameters", {"type": "object"})} for t in body["tools"]]}]
    return out


def _gemini_parse(d):
    cand = (d.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    tcs = [{"id": "call_" + uuid.uuid4().hex[:10], "type": "function",
            "function": {"name": p["functionCall"]["name"], "arguments": json.dumps(p["functionCall"].get("args", {}))}}
           for p in parts if "functionCall" in p]
    u = d.get("usageMetadata", {})
    usage = {"prompt_tokens": u.get("promptTokenCount", 0), "completion_tokens": u.get("candidatesTokenCount", 0),
             "total_tokens": u.get("totalTokenCount", 0)}
    fin = cand.get("finishReason")
    finish = "tool_calls" if tcs else ({"MAX_TOKENS": "length"}.get(fin, "stop") if fin else None)
    return text, tcs, usage, finish


class Gemini(Provider):
    name = "gemini"

    async def complete(self, model, body, key):
        r = await self._post(f"{self.base}/models/{model}:generateContent", {"x-goog-api-key": key}, openai_to_gemini(body))
        text, tcs, usage, finish = _gemini_parse(r.json())
        msg = {"role": "assistant", "content": text or None}
        if tcs:
            msg["tool_calls"] = tcs
        return {"id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion", "created": int(time.time()),
                "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": finish or "stop"}], "usage": usage}

    async def stream(self, model, body, key):
        r = await self._post(f"{self.base}/models/{model}:streamGenerateContent?alt=sse", {"x-goog-api-key": key},
                             openai_to_gemini(body), stream=True)
        try:
            async for d in _sse_lines(r):
                text, tcs, usage, finish = _gemini_parse(json.loads(d))
                delta = {}
                if text:
                    delta["content"] = text
                if tcs:
                    delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(tcs)]
                yield _chunk(model, delta, finish, usage if finish else None)
        finally:
            await r.aclose()


PROVIDER_CLASSES = {c.name: c for c in (OpenAICompatible, DeepSeek, SelfHosted, Anthropic, Gemini)}
