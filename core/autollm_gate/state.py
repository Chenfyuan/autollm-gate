"""跨进程共享状态：会话粘性、限流计数、上游监控分钟桶、配置变更广播、分布式锁。

设置 REDIS_URL 时使用 Redis（多实例部署必须）；否则退化为进程内内存实现（单进程 / 测试）。
"""
from __future__ import annotations
import asyncio, logging, os, time
from typing import Awaitable, Callable

log = logging.getLogger("autollm_gate.state")
Handler = Callable[[str], Awaitable[None]]


class MemoryState:
    kind = "memory"

    def __init__(self):
        self._kv: dict[str, tuple[str, float]] = {}
        self._h: dict[str, tuple[dict, float]] = {}
        self._subs: dict[str, list[Handler]] = {}

    def _alive(self, exp):
        return exp == 0 or exp > time.time()

    async def get(self, k):
        v = self._kv.get(k)
        return v[0] if v and self._alive(v[1]) else None

    async def set(self, k, v, ttl: int = 0, nx: bool = False) -> bool:
        if nx and await self.get(k) is not None:
            return False
        self._kv[k] = (str(v), time.time() + ttl if ttl else 0)
        return True

    async def delete(self, k):
        self._kv.pop(k, None)

    async def incr(self, k, ttl: int) -> int:
        cur = await self.get(k)
        n = int(cur or 0) + 1
        exp = self._kv[k][1] if cur is not None else time.time() + ttl
        self._kv[k] = (str(n), exp)
        return n

    async def hincr(self, k, fields: dict, ttl: int):
        h = self._h.get(k)
        if not h or not self._alive(h[1]):
            h = ({}, time.time() + ttl)
        for f, v in fields.items():
            h[0][f] = h[0].get(f, 0) + v
        self._h[k] = h

    async def hgetall(self, k) -> dict:
        h = self._h.get(k)
        return dict(h[0]) if h and self._alive(h[1]) else {}

    async def publish(self, channel, msg):
        for fn in self._subs.get(channel, []):
            await fn(msg)

    async def subscribe(self, channel, fn: Handler):
        self._subs.setdefault(channel, []).append(fn)

    async def ping(self) -> bool:
        return True

    async def close(self):
        pass


class RedisState(MemoryState):
    kind = "redis"

    def __init__(self, url: str | None = None, client=None):
        super().__init__()
        if client is None:
            import redis.asyncio as aioredis
            client = aioredis.from_url(url, decode_responses=True)
        self.r = client
        self._tasks: list[asyncio.Task] = []

    async def get(self, k):
        return await self.r.get(k)

    async def set(self, k, v, ttl: int = 0, nx: bool = False) -> bool:
        return bool(await self.r.set(k, v, ex=ttl or None, nx=nx))

    async def delete(self, k):
        await self.r.delete(k)

    async def incr(self, k, ttl: int) -> int:
        p = self.r.pipeline()
        p.incr(k)
        p.expire(k, ttl, nx=True)
        n, _ = await p.execute()
        return int(n)

    async def hincr(self, k, fields: dict, ttl: int):
        p = self.r.pipeline()
        for f, v in fields.items():
            (p.hincrbyfloat if isinstance(v, float) else p.hincrby)(k, f, v)
        p.expire(k, ttl)
        await p.execute()

    async def hgetall(self, k) -> dict:
        return {f: float(v) for f, v in (await self.r.hgetall(k)).items()}

    async def publish(self, channel, msg):
        await self.r.publish(channel, msg)

    async def subscribe(self, channel, fn: Handler):
        ps = self.r.pubsub()
        await ps.subscribe(channel)

        async def loop():
            while True:
                try:
                    m = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if m and m.get("type") == "message":
                        await fn(m["data"])
                except asyncio.CancelledError:
                    raise
                except Exception:  # 断线等：稍后重试，不影响请求
                    log.exception("pubsub loop error")
                    await asyncio.sleep(1)
        self._tasks.append(asyncio.create_task(loop()))

    async def ping(self) -> bool:
        try:
            return bool(await self.r.ping())
        except Exception:
            return False

    async def close(self):
        for t in self._tasks:
            t.cancel()
        try:
            await self.r.aclose()
        except Exception:
            pass


def make_state(url: str | None = None):
    url = url if url is not None else os.getenv("REDIS_URL", "")
    return RedisState(url) if url else MemoryState()
