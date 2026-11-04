"""OpenAI Responses API (/v1/responses) <-> 内部 Chat Completions 格式互转，供 Codex CLI 等客户端使用。"""
from __future__ import annotations
import json, time, uuid


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


def responses_to_chat(body: dict) -> dict:
    msgs = []
    if body.get("instructions"):
        msgs.append({"role": "system", "content": body["instructions"]})
    inp = body.get("input")
    if isinstance(inp, str):
        msgs.append({"role": "user", "content": inp})
    for it in inp if isinstance(inp, list) else []:
        t = it.get("type", "message")
        if t == "message":
            role = it.get("role", "user")
            msgs.append({"role": "system" if role == "developer" else role, "content": _text(it.get("content"))})
        elif t == "function_call":
            tc = {"id": it.get("call_id") or it.get("id"), "type": "function",
                  "function": {"name": it["name"], "arguments": it.get("arguments") or "{}"}}
            if msgs and msgs[-1]["role"] == "assistant" and msgs[-1].get("tool_calls") is not None:
                msgs[-1]["tool_calls"].append(tc)
            else:
                msgs.append({"role": "assistant", "content": None, "tool_calls": [tc]})
        elif t == "function_call_output":
            out = it.get("output")
            msgs.append({"role": "tool", "tool_call_id": it.get("call_id"), "content": out if isinstance(out, str) else json.dumps(out)})
        # reasoning 等其它条目忽略
    out = {"model": body.get("model", "auto"), "messages": msgs, "stream": bool(body.get("stream"))}
    if body.get("max_output_tokens"):
        out["max_tokens"] = body["max_output_tokens"]
    for k in ("temperature", "top_p", "user", "prompt_cache_key", "metadata"):
        if k in body:
            out[k] = body[k]
    tools = [t for t in body.get("tools") or [] if t.get("type") == "function"]
    if tools:
        out["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                          "parameters": t.get("parameters") or {"type": "object"}}} for t in tools]
    return out


def _usage(u: dict) -> dict:
    i, o = int(u.get("prompt_tokens", 0) or 0), int(u.get("completion_tokens", 0) or 0)
    return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o}


def _resp(rid, model, output, usage, status="completed", created=None):
    return {"id": rid, "object": "response", "created_at": created or int(time.time()), "status": status, "model": model,
            "output": output, "usage": usage, "error": None, "incomplete_details": None}


def chat_to_response(resp: dict, model: str) -> dict:
    m = resp["choices"][0]["message"]
    output = []
    if m.get("content"):
        output.append({"type": "message", "id": "msg_" + uuid.uuid4().hex[:24], "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": m["content"], "annotations": []}]})
    for tc in m.get("tool_calls") or []:
        output.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:24], "call_id": tc["id"],
                       "name": tc["function"]["name"], "arguments": tc["function"].get("arguments") or "{}", "status": "completed"})
    return _resp("resp_" + uuid.uuid4().hex[:24], model, output, _usage(resp.get("usage") or {}))


async def chat_stream_to_responses(chunks, model: str, usage_out: dict):
    """把 Chat chunk 异步流转成 Responses SSE 事件。"""
    rid, created, seq = "resp_" + uuid.uuid4().hex[:24], int(time.time()), 0

    def ev(t, **d):
        nonlocal seq
        seq += 1
        return f"event: {t}\ndata: {json.dumps({'type': t, 'sequence_number': seq, **d}, ensure_ascii=False)}\n\n"

    yield ev("response.created", response=_resp(rid, model, [], None, "in_progress", created))
    yield ev("response.in_progress", response=_resp(rid, model, [], None, "in_progress", created))
    output: list[dict] = []
    text_item = None
    text = ""
    calls: dict[int, dict] = {}

    def close_text():
        nonlocal text_item
        if text_item is None:
            return []
        idx = output.index(text_item)
        part = {"type": "output_text", "text": text, "annotations": []}
        text_item.update(status="completed", content=[part])
        evs = [ev("response.output_text.done", item_id=text_item["id"], output_index=idx, content_index=0, text=text),
               ev("response.content_part.done", item_id=text_item["id"], output_index=idx, content_index=0, part=part),
               ev("response.output_item.done", output_index=idx, item=text_item)]
        text_item = None
        return evs

    async for c in chunks:
        if c.get("usage"):
            usage_out.update(c["usage"])
        for ch in c.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                if text_item is None:
                    text_item = {"type": "message", "id": "msg_" + uuid.uuid4().hex[:24], "role": "assistant", "status": "in_progress", "content": []}
                    output.append(text_item)
                    idx = len(output) - 1
                    yield ev("response.output_item.added", output_index=idx, item=text_item)
                    yield ev("response.content_part.added", item_id=text_item["id"], output_index=idx, content_index=0,
                             part={"type": "output_text", "text": "", "annotations": []})
                text += d["content"]
                yield ev("response.output_text.delta", item_id=text_item["id"], output_index=output.index(text_item),
                         content_index=0, delta=d["content"])
            for tc in d.get("tool_calls") or []:
                ti = tc.get("index", 0)
                if ti not in calls:
                    for e in close_text():
                        yield e
                    item = {"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:24], "call_id": tc.get("id") or "call_" + uuid.uuid4().hex[:16],
                            "name": (tc.get("function") or {}).get("name", ""), "arguments": "", "status": "in_progress"}
                    calls[ti] = item
                    output.append(item)
                    yield ev("response.output_item.added", output_index=len(output) - 1, item=item)
                args = (tc.get("function") or {}).get("arguments")
                if args:
                    calls[ti]["arguments"] += args
                    yield ev("response.function_call_arguments.delta", item_id=calls[ti]["id"],
                             output_index=output.index(calls[ti]), delta=args)
    for e in close_text():
        yield e
    for item in calls.values():
        idx = output.index(item)
        item["status"] = "completed"
        yield ev("response.function_call_arguments.done", item_id=item["id"], output_index=idx, arguments=item["arguments"])
        yield ev("response.output_item.done", output_index=idx, item=item)
    yield ev("response.completed", response=_resp(rid, model, output, _usage(usage_out), "completed", created))
