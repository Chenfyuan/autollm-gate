"""压测 / 故障切换测量工具（只打本地网关 + 假上游）。

压测：  python scripts/loadtest.py load  --base http://127.0.0.1:8080 --key sk-lr-... --concurrency 50 --seconds 60
切换：  python scripts/loadtest.py probe --base ... --key ... --rps 20 --seconds 90 --out /tmp/probe.jsonl
        （运行期间手动停掉 / 恢复某个假上游，结束后输出切换与恢复时间）
"""
import argparse, asyncio, json, statistics, time
import httpx

BODY = {"model": "auto", "messages": [{"role": "user", "content": "你好，压测请求"}], "max_tokens": 64}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else None


async def load(a):
    lat, codes = [], {}
    stop = time.monotonic() + a.seconds
    limits = httpx.Limits(max_connections=a.concurrency * 2, max_keepalive_connections=a.concurrency * 2)
    async with httpx.AsyncClient(base_url=a.base, timeout=30, limits=limits, headers={"Authorization": f"Bearer {a.key}"}) as c:
        async def worker():
            while time.monotonic() < stop:
                t0 = time.perf_counter()
                try:
                    r = await c.post("/v1/chat/completions", json=BODY)
                    code = r.status_code
                except Exception as e:
                    code = type(e).__name__
                lat.append((time.perf_counter() - t0) * 1000)
                codes[code] = codes.get(code, 0) + 1
        t0 = time.monotonic()
        await asyncio.gather(*[worker() for _ in range(a.concurrency)])
        el = time.monotonic() - t0
    n = sum(codes.values())
    ok = codes.get(200, 0)
    res = {"concurrency": a.concurrency, "seconds": round(el, 1), "requests": n, "rps": round(n / el, 1),
           "p50_ms": round(pct(lat, 0.5), 1), "p95_ms": round(pct(lat, 0.95), 1), "p99_ms": round(pct(lat, 0.99), 1),
           "mean_ms": round(statistics.mean(lat), 1), "error_rate_pct": round((n - ok) / n * 100, 3), "codes": codes}
    print(json.dumps(res, ensure_ascii=False))


async def probe(a):
    out = open(a.out, "w")
    async with httpx.AsyncClient(base_url=a.base, timeout=30, headers={"Authorization": f"Bearer {a.key}"}) as c:
        async def one():
            t0 = time.time()
            try:
                r = await c.post("/v1/chat/completions", json=BODY)
                rec = {"t": t0, "code": r.status_code, "provider": r.headers.get("x-router-provider"), "attempts": r.headers.get("x-router-attempts"),
                       "reason": r.headers.get("x-router-reason", "")[:120]}
            except Exception as e:
                rec = {"t": t0, "code": type(e).__name__}
            rec["ms"] = round((time.time() - t0) * 1000, 1)
            out.write(json.dumps(rec) + "\n"); out.flush()
        tasks = []
        end = time.time() + a.seconds
        while time.time() < end:
            tasks.append(asyncio.create_task(one()))
            await asyncio.sleep(1 / a.rps)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["load", "probe"])
    p.add_argument("--base", default="http://127.0.0.1:8080")
    p.add_argument("--key", required=True)
    p.add_argument("--concurrency", type=int, default=50)
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--rps", type=float, default=20)
    p.add_argument("--out", default="/tmp/probe.jsonl")
    a = p.parse_args()
    asyncio.run(load(a) if a.mode == "load" else probe(a))
