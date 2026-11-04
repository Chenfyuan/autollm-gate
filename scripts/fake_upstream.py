"""测试用假上游（OpenAI 兼容 /v1/chat/completions，支持流式）。不发任何真实请求。

uvicorn --app-dir scripts fake_upstream:app --port 9000      环境变量 FAKE_LATENCY_MS 模拟上游耗时
"""
import asyncio, json, os, random
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
LAT = float(os.getenv("FAKE_LATENCY_MS", "30")) / 1000


@app.post("/v1/chat/completions")
async def chat(r: Request):
    b = await r.json()
    await asyncio.sleep(LAT * random.uniform(0.7, 1.3))
    usage = {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180}
    if b.get("stream"):
        async def g():
            for w in ("你好", "，我是", "假上游"):
                yield f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': w}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
            yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(g(), media_type="text/event-stream")
    return {"id": "x", "object": "chat.completion", "model": b["model"], "usage": usage,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "假上游回复：" + b["model"]}, "finish_reason": "stop"}]}
