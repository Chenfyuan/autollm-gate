"""每个上游（provider）一个熔断器：连续失败达到阈值即熔断，冷却后半开放行一个探测请求，成功则恢复。

熔断状态在进程内维护（每个副本独立判断，避免共享状态成为单点）；监控数据通过 state 汇总到 Redis。
"""
from __future__ import annotations
import os, time

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitBreaker:
    def __init__(self, threshold: int | None = None, cooldown: float | None = None):
        self.threshold = threshold or int(os.getenv("BREAKER_FAILURE_THRESHOLD", "5"))
        self.cooldown = cooldown if cooldown is not None else float(os.getenv("BREAKER_COOLDOWN_SECONDS", "15"))
        self.failures = 0
        self.state = CLOSED
        self.opened_at = 0.0
        self.probing = False

    def allow(self) -> bool:
        if self.state == CLOSED:
            return True
        if self.state == OPEN and time.monotonic() - self.opened_at >= self.cooldown:
            self.state, self.probing = HALF_OPEN, False
        if self.state == HALF_OPEN and not self.probing:
            self.probing = True  # 只放行一个探测请求
            return True
        return False

    def success(self):
        self.failures, self.state, self.probing = 0, CLOSED, False

    def failure(self):
        self.failures += 1
        if self.state == HALF_OPEN or self.failures >= self.threshold:
            self.state, self.opened_at, self.probing = OPEN, time.monotonic(), False


class Breakers:
    def __init__(self, **kw):
        self.kw, self.d = kw, {}

    def get(self, provider) -> CircuitBreaker:
        if provider not in self.d:
            self.d[provider] = CircuitBreaker(**self.kw)
        return self.d[provider]

    def snapshot(self):
        return {p: {"state": b.state, "failures": b.failures} for p, b in self.d.items()}
