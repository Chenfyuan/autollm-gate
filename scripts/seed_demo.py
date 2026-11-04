"""生成演示数据：若干租户（含一个可登录的演示租户）、30 天历史用量、充值记录。

用法：DATABASE_URL=... DEMO_TENANT_EMAIL=... DEMO_TENANT_PASSWORD=... python scripts/seed_demo.py
仅用于演示 / 验收环境，请勿在生产库执行。
"""
import asyncio, os, random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from autollm_admin.billing import Pricing, hash_key, new_api_key
from autollm_admin.db import MICRO, ApiKey, Tenant, TenantUser, Topup, Usage, make_engine, make_sessionmaker
from autollm_admin.security import hash_password
from autollm_gate.router import load_config

TENANTS = [  # 名称, 邮箱, 日均请求, 主力模型
    ("星河科技", None, 260, ["deepseek-chat", "gpt-4o-mini", "claude-sonnet-4-5", "qwen3-32b", "gemini-2.5-flash"]),
    ("北辰数据", "ops@beichen.example", 180, ["gpt-4o", "claude-haiku-4-5", "deepseek-chat"]),
    ("青岚教育", "dev@qinglan.example", 120, ["gemini-2.5-flash", "deepseek-chat", "qwen3-32b"]),
    ("木棉智能", "ai@mumian.example", 75, ["claude-sonnet-4-5", "gpt-4o"]),
    ("远山工作室", "hi@yuanshan.example", 30, ["deepseek-reasoner", "gpt-4o-mini"]),
    ("拾光文创", "team@shiguang.example", 12, ["gpt-4o-mini"]),
]


async def main():
    random.seed(42)
    engine = make_engine()
    S = make_sessionmaker(engine)
    pricing = Pricing(load_config())
    demo_email = os.environ.get("DEMO_TENANT_EMAIL", "demo@autollm.example").lower()
    demo_pw = os.environ["DEMO_TENANT_PASSWORD"]
    now = datetime.now(timezone.utc)
    async with S() as s:
        if await s.scalar(select(TenantUser).where(TenantUser.email == demo_email)):
            print("演示数据已存在，跳过")
            return
        for i, (name, email, per_day, models) in enumerate(TENANTS):
            email = email or demo_email
            created = now - timedelta(days=random.randint(35, 120))
            t = Tenant(name=name, created_at=created, markup_pct=None, balance_micro=0)
            s.add(t)
            await s.flush()
            s.add(TenantUser(tenant_id=t.id, email=email, name="张伟" if i == 0 else "", created_at=created,
                             password_hash=hash_password(demo_pw if email == demo_email else os.urandom(16).hex() + "a1"),
                             last_login_at=now - timedelta(hours=random.randint(1, 72))))
            keys = []
            for kn in (["生产环境", "Claude Code", "测试"] if i == 0 else ["默认"]):
                raw = new_api_key()
                k = ApiKey(tenant_id=t.id, name=kn, prefix=raw[:10], key_hash=hash_key(raw), created_at=created + timedelta(days=1),
                           last_used_at=now - timedelta(minutes=random.randint(1, 300)))
                s.add(k)
                keys.append(k)
            await s.flush()
            spent = 0
            for d in range(30, -1, -1):
                day = now - timedelta(days=d)
                trend = 0.6 + 0.4 * (30 - d) / 30
                weekend = 0.55 if day.weekday() >= 5 else 1
                n = max(0, int(per_day * trend * weekend * random.uniform(0.8, 1.2) / 6))  # 每条记录代表一批请求，控制行数
                for _ in range(n):
                    m = random.choices(models, weights=[len(models) - j for j in range(len(models))])[0]
                    src = "selfhosted" if pricing.cfg["models"][m]["provider"] == "selfhosted" else "platform"
                    pt, ct = random.randint(800, 9000) * 6, random.randint(150, 1600) * 6
                    cost = pricing.cost_micro(m, pt, ct)
                    charge = pricing.charge_micro(cost, src, None)
                    ts = day.replace(hour=random.randint(0, 23), minute=random.randint(0, 59), second=random.randint(0, 59))
                    if ts > now:
                        ts = now - timedelta(minutes=random.randint(1, 50))
                    s.add(Usage(tenant_id=t.id, api_key_id=random.choice(keys).id, model=m, provider=pricing.cfg["models"][m]["provider"],
                                key_source=src, strategy=random.choice(["cost_optimized", "explicit", "balanced"]), prompt_tokens=pt,
                                completion_tokens=ct, cost_micro=cost, charge_micro=charge, latency_ms=random.randint(380, 4200), status="ok", created_at=ts))
                    spent += charge
            total = 0
            for j, amt in enumerate([50, 100, 200, 500][: 2 + i % 3] if i < 5 else [5]):
                total += amt * MICRO
                s.add(Topup(tenant_id=t.id, amount_micro=amt * MICRO, channel="manual", status="paid", note="对公转账",
                            created_at=created + timedelta(days=2 + j * 9), paid_at=created + timedelta(days=2 + j * 9)))
            need = spent + (random.randint(20, 160) * MICRO if i < 5 else 300_000)
            if total < need:
                extra = (need - total) // MICRO + 1
                s.add(Topup(tenant_id=t.id, amount_micro=extra * MICRO, channel="manual", status="paid", note="补充额度",
                            created_at=now - timedelta(days=3), paid_at=now - timedelta(days=3)))
                total += extra * MICRO
            t.balance_micro = total - spent
            if i == 2:
                t.monthly_token_limit = 900_000_000
        await s.commit()
    await engine.dispose()
    print("演示数据已生成")


if __name__ == "__main__":
    asyncio.run(main())
