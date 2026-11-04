"""Prometheus 指标 + 写入共享状态的分钟级监控桶（供后台监控页跨实例汇总）。"""
from __future__ import annotations
import time
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

REGISTRY = CollectorRegistry()
REQUESTS = Counter("autollm_http_requests_total", "网关 HTTP 请求数", ["endpoint", "code"], registry=REGISTRY)
UPSTREAM = Counter("autollm_upstream_requests_total", "上游调用次数", ["provider", "outcome"], registry=REGISTRY)
UPSTREAM_LAT = Histogram("autollm_upstream_latency_seconds", "上游首包/完成延迟", ["provider"], registry=REGISTRY,
                         buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60))
BREAKER = Gauge("autollm_breaker_open", "熔断器状态（1=熔断/半开）", ["provider"], registry=REGISTRY)
FAILOVERS = Counter("autollm_failovers_total", "降级切换次数", ["from_provider"], registry=REGISTRY)
RATE_LIMITED = Counter("autollm_rate_limited_total", "被限流的请求数", ["scope"], registry=REGISTRY)
TOKENS = Counter("autollm_tokens_total", "计量 token 数", ["model", "kind"], registry=REGISTRY)

LAT_BUCKETS_MS = (100, 250, 500, 1000, 2000, 5000, 10000, 30000)
MON_TTL = 3 * 3600


def mon_key(minute: int, provider: str) -> str:
    return f"mon:{minute}:{provider}"


async def record_upstream(state, provider: str, ok: bool, latency_s: float):
    UPSTREAM.labels(provider, "ok" if ok else "error").inc()
    UPSTREAM_LAT.labels(provider).observe(latency_s)
    ms = latency_s * 1000
    fields = {"req": 1, "err": 0 if ok else 1, "lat_sum": round(ms, 1)}
    b = next((x for x in LAT_BUCKETS_MS if ms <= x), "inf")
    fields[f"le_{b}"] = 1
    minute = int(time.time() // 60)
    try:
        await state.hincr(mon_key(minute, provider), fields, MON_TTL)
        await state.set(f"mon:providers:{provider}", "1", ttl=MON_TTL)
    except Exception:
        pass


def _quantile(buckets: dict, total: float, q: float):
    if not total:
        return None
    acc = 0.0
    for b in LAT_BUCKETS_MS:
        acc += buckets.get(f"le_{b}", 0)
        if acc >= total * q:
            return b
    return LAT_BUCKETS_MS[-1]


async def summarize(state, providers, minutes: int = 15):
    """返回 {provider: {req, err, error_rate, p50_ms, p95_ms, avg_ms, series:[{t, req, err}]}}"""
    now_m = int(time.time() // 60)
    out = {}
    for p in providers:
        tot = {}
        series = []
        for m in range(now_m - minutes + 1, now_m + 1):
            h = await state.hgetall(mon_key(m, p))
            series.append({"t": m * 60, "req": int(h.get("req", 0)), "err": int(h.get("err", 0)),
                           "avg_ms": round(h["lat_sum"] / h["req"]) if h.get("req") else None})
            for k, v in h.items():
                tot[k] = tot.get(k, 0) + float(v)
        req, err = int(tot.get("req", 0)), int(tot.get("err", 0))
        out[p] = {"req": req, "err": err, "error_rate": round(err / req, 4) if req else 0.0,
                  "avg_ms": round(tot["lat_sum"] / req) if req else None,
                  "p50_ms": _quantile(tot, req, 0.5), "p95_ms": _quantile(tot, req, 0.95), "series": series}
    return out


def render():
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
