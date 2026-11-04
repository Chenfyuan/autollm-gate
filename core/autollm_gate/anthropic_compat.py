"""Anthropic Messages API (/v1/messages) <-> 内部 OpenAI 格式互转，供 Claude Code 等客户端直连。"""
from __future__ import annotations
import json, uuid


def _blocks(c):
    return [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])


def messages_to_openai(body: dict) -> dict:
    msgs = []
    sysv = body.get("system")
    if sysv:
        msgs.append({"role": "system", "content": sysv if isinstance(sysv, str) else "".join(b.get("text", "") for b in sysv)})
    for m in body.get("messages", []):
        blocks = _blocks(m.get("content"))
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            tcs = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                   for b in blocks if b.get("type") == "tool_use"]
            om = {"role": "assistant", "content": text or None}
            if tcs:
                om["tool_calls"] = tcs
            msgs.append(om)
        else:
            texts = []
            for b in blocks:
                if b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
                    msgs.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c or ""})
                elif b.get("type") == "text":
                    texts.append(b["text"])
            if texts:
                msgs.append({"role": "user", "content": "\n".join(texts)})
    out = {"model": body.get("model", "auto"), "messages": msgs, "max_tokens": body.get("max_tokens", 4096)}
    for k in ("temperature", "top_p", "metadata"):
        if k in body:
            out[k] = body[k]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                          "parameters": t.get("input_schema", {"type": "object"})}}
                        for t in body["tools"] if "name" in t]
    return out


_STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def openai_to_message(resp: dict, model: str) -> dict:
    ch = resp["choices"][0]
    m = ch["message"]
    content = []
    if m.get("content"):
        content.append({"type": "text", "text": m["content"]})
    for tc in m.get("tool_calls") or []:
        content.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                        "input": json.loads(tc["function"].get("arguments") or "{}")})
    u = resp.get("usage") or {}
    return {"id": "msg_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": _STOP.get(ch.get("finish_reason"), "end_turn"), "stop_sequence": None,
            "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}}


def _ev(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def openai_stream_to_anthropic(chunks, model: str, usage_out: dict):
    """把 OpenAI chunk 异步流转成 Anthropic SSE 事件。usage_out 用于回填计量。"""
    yield _ev("message_start", {"type": "message_start", "message": {"id": "msg_" + uuid.uuid4().hex[:20], "type": "message",
              "role": "assistant", "model": model, "content": [], "stop_reason": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})
    idx, cur, tool_map, finish = -1, None, {}, None
    async for c in chunks:
        if c.get("usage"):
            usage_out.update(c["usage"])
        for ch in c.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                if cur != "text":
                    if cur is not None:
                        yield _ev("content_block_stop", {"type": "content_block_stop", "index": idx})
                    idx += 1; cur = "text"
                    yield _ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": {"type": "text", "text": ""}})
                yield _ev("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": {"type": "text_delta", "text": d["content"]}})
            for tc in d.get("tool_calls") or []:
                ti = tc.get("index", 0)
                if ti not in tool_map:
                    if cur is not None:
                        yield _ev("content_block_stop", {"type": "content_block_stop", "index": idx})
                    idx += 1; cur = f"tool{ti}"; tool_map[ti] = idx
                    yield _ev("content_block_start", {"type": "content_block_start", "index": idx, "content_block": {
                        "type": "tool_use", "id": tc.get("id") or "toolu_" + uuid.uuid4().hex[:16], "name": tc["function"]["name"], "input": {}}})
                args = (tc.get("function") or {}).get("arguments")
                if args:
                    yield _ev("content_block_delta", {"type": "content_block_delta", "index": tool_map[ti],
                                                      "delta": {"type": "input_json_delta", "partial_json": args}})
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    if cur is not None:
        yield _ev("content_block_stop", {"type": "content_block_stop", "index": idx})
    yield _ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": _STOP.get(finish, "end_turn"), "stop_sequence": None},
                                "usage": {"input_tokens": usage_out.get("prompt_tokens", 0), "output_tokens": usage_out.get("completion_tokens", 0)}})
    yield _ev("message_stop", {"type": "message_stop"})
