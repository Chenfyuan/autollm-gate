"""告警：上游错误率突增、租户余额不足、月度额度即将耗尽。

每个实例都跑评估循环，但通过 Redis 锁选主，同一时刻只有一个实例评估和发送；同一告警在冷却期内只发一次。
告警写入 alert_events 表（后台「监控告警」页展示），并可推送到 Webhook（通用 JSON / 飞书 / 企业微信 / 钉钉 / Slack）。
"""
from __future__ import annotations
import asyncio, json, logging, os
from datetime import datetime, timezone
import httpx

from .webhook_guard import WebhookURLError, pinned_target, validate_webhook_url
from sqlalchemy import func, select

from autollm_gate.metrics import summarize
from autollm_gate.providers import PROVIDER_CLASSES
from .db import MICRO, AlertEvent, Setting, Tenant, Usage, now

log = logging.getLogger("autollm_admin.alerts")

DEFAULTS = {
    "alert_enabled": "1",
    "alert_webhook_url": "",
    "alert_webhook_format": "generic",   # generic / feishu / wecom / dingtalk / slack
    "alert_error_rate_pct": "20",        # 5 分钟内上游错误率 ≥ 该值
    "alert_min_requests": "20",          # 且请求数 ≥ 该值才判定
    "alert_low_balance_usd": "1",        # 租户可用余额低于该值
    "alert_quota_pct": "90",             # 月度 token 额度使用率 ≥ 该值
    "alert_cooldown_minutes": "30",
}


def alert_settings(raw: dict) -> dict:
    return {k: raw.get(k, v) for k, v in DEFAULTS.items()}


def webhook_payload(fmt: str, title: str, message: str, severity: str, kind: str) -> dict:
    text = f"[AutoLLM Gate][{severity}] {title}\n{message}"
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if fmt == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "dingtalk":
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "slack":
        return {"text": text}
    return {"source": "autollm-gate", "kind": kind, "severity": severity, "title": title, "message": message,
            "text": text, "fired_at": now().isoformat()}


class Alerter:
    def __init__(self, Session, state, pricing, client: httpx.AsyncClient | None = None):
        self.Session, self.state, self.pricing = Session, state, pricing
        self.client = client or httpx.AsyncClient(timeout=10)
        self.interval = float(os.getenv("ALERT_INTERVAL_SECONDS", "30"))
        self._task: asyncio.Task | None = None

    def cfg(self) -> dict:
        return alert_settings(self.pricing.raw)

    async def fire(self, kind: str, key: str, title: str, message: str, severity: str = "warning", force: bool = False) -> AlertEvent | None:
        c = self.cfg()
        cooldown = int(float(c["alert_cooldown_minutes"]) * 60)
        if not force and not await self.state.set(f"alert:sent:{key}", "1", ttl=max(cooldown, 1), nx=True):
            return None
        ev = AlertEvent(kind=kind, key=key, severity=severity, title=title, message=message)
        url = c["alert_webhook_url"].strip()
        if url:
            try:
                ip = await validate_webhook_url(url)
                target, hdrs, ext = pinned_target(url, ip)  # 直连已校验 IP，防 DNS rebinding
                r = await self.client.post(target, headers=hdrs, extensions=ext,
                                           json=webhook_payload(c["alert_webhook_format"], title, message, severity, kind))
                ev.delivered = r.status_code < 300
                if not ev.delivered:
                    ev.delivery_error = f"HTTP {r.status_code}"
            except WebhookURLError as e:
                ev.delivery_error = f"已拦截：{e}"
            except Exception as e:
                ev.delivery_error = str(e)[:500]
        async with self.Session() as s:
            s.add(ev)
            await s.commit()
        log.warning("alert fired", extra={"f_kind": kind, "f_key": key, "f_title": title, "f_delivered": ev.delivered})
        return ev

    async def evaluate(self) -> list[AlertEvent]:
        c = self.cfg()
        if c["alert_enabled"] != "1":
            return []
        fired = []
        # 1) 上游错误率
        stats = await summarize(self.state, list(PROVIDER_CLASSES), minutes=5)
        thr, min_req = float(c["alert_error_rate_pct"]), int(float(c["alert_min_requests"]))
        for p, st in stats.items():
            if st["req"] >= min_req and st["error_rate"] * 100 >= thr:
                ev = await self.fire("upstream_error", f"upstream:{p}", f"上游 {p} 错误率 {st['error_rate'] * 100:.0f}%",
                                     f"最近 5 分钟 {st['req']} 次调用中 {st['err']} 次失败（阈值 {thr:.0f}%）。网关已自动降级到其它上游，请检查该上游 Key 与服务状态。",
                                     "critical")
                if ev:
                    fired.append(ev)
        # 2) 余额不足 / 3) 额度即将耗尽
        low = round(float(c["alert_low_balance_usd"]) * MICRO)
        start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self.Session() as s:
            used_tenants = set(await s.scalars(select(Usage.tenant_id).distinct()))
            tenants = (await s.scalars(select(Tenant).where(Tenant.active.is_(True)))).all()
            usage = dict((await s.execute(select(Usage.tenant_id, func.sum(Usage.prompt_tokens + Usage.completion_tokens))
                                          .where(Usage.created_at >= start).group_by(Usage.tenant_id))).all())
        for t in tenants:
            if t.id in used_tenants and t.balance_micro < low:
                ev = await self.fire("low_balance", f"balance:{t.id}", f"租户「{t.name}」余额不足",
                                     f"可用余额 ${t.balance_micro / MICRO:.4f}，低于告警阈值 ${low / MICRO:.2f}。")
                if ev:
                    fired.append(ev)
            if t.monthly_token_limit:
                pct = (usage.get(t.id) or 0) / t.monthly_token_limit * 100
                if pct >= float(c["alert_quota_pct"]):
                    ev = await self.fire("quota", f"quota:{t.id}:{start:%Y%m}", f"租户「{t.name}」本月额度已用 {pct:.0f}%",
                                         f"本月已用 {usage.get(t.id) or 0:,} / {t.monthly_token_limit:,} tokens。")
                    if ev:
                        fired.append(ev)
        return fired

    async def loop(self):
        while True:
            try:
                await asyncio.sleep(self.interval)
                if await self.state.set("alert:leader", "1", ttl=max(int(self.interval) - 1, 1), nx=True):
                    await self.evaluate()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("alert evaluation failed")

    async def start(self, app):
        if os.getenv("ALERTS_DISABLED") != "1":
            self._task = asyncio.create_task(self.loop())

    async def stop(self, app):
        if self._task:
            self._task.cancel()
