# 部署与配置详解

一个兼容 OpenAI / Anthropic / Responses 协议的大模型网关：`model: "auto"` 时按任务类型与成本自动选模型，失败自动切换；自带多租户计费、开发者控制台与运营后台。

## 功能概览

**网关**
- 接口：`/v1/chat/completions`、`/v1/messages`、`/v1/responses`（均支持流式与非流式）
- 自动路由 + 会话粘性（Redis 共享，多实例一致）
- 失败切换：上游 429 / 5xx / 超时自动换下一个候选；4xx 参数错误直接返回、不计入熔断
- 熔断器：连续失败达到阈值后暂停调用该上游，冷却后放行一个探测请求，成功即恢复
- 健康检查 `/healthz`、就绪检查 `/readyz`（检查数据库与 Redis）、Prometheus 指标 `/metrics`（可用 `METRICS_TOKEN` 保护）
- 结构化 JSON 日志

**计费**
- 预扣/结算：请求前按最贵候选模型冻结额度（单条 SQL 原子条件更新，绝不透支），完成后按实际用量结算、多退少补
- 平台统一加价、租户单独加价、自带密钥服务费，修改后通过 Redis 广播到所有实例立即生效

**开发者控制台**（`/`）：注册/登录、概览、用量分析、账单明细、API 密钥（只在创建时显示一次）、余额充值、模型与价格、快速开始。

**运营后台**（`/admin`）：运营概览、租户管理（可下钻）、模型与价格、上游密钥（加密存储、只显示掩码）、监控告警（各上游错误率/延迟/熔断状态）、计费与告警设置、管理员账号。

**安全**
- 密码 argon2id 哈希；登录态为 HttpOnly + SameSite 的签名 JWT Cookie，配合 CSRF 头校验；改密/禁用即吊销会话
- 上游密钥用 `MASTER_KEY` 加密落库
- 注册、登录、API 调用均有限流（按 IP / 按密钥 RPM）
- 告警 Webhook 防 SSRF：生产环境只允许 https；保存时和每次发送前都会解析域名，拒绝内网、本机、链路本地、保留和组播地址（IPv4/IPv6）
- 只有 ha 模式（网关仅经 nginx 访问、nginx 用真实来源地址覆盖 `X-Forwarded-For` / `X-Real-IP`）才开启 `TRUST_PROXY`；单实例默认关闭
- 生产环境（`ENV=production`）拒绝开启模拟支付、拒绝过短的 `SESSION_SECRET`

**告警**：上游错误率突增、租户余额不足、月度额度将满，推送到 Webhook（支持通用 JSON / 飞书 / 企业微信 / 钉钉 / Slack），同一告警在冷却期内只发一次；多实例时通过 Redis 选主，只有一个实例负责评估。另附 Prometheus 告警规则 `deploy/prometheus/alerts.yml`。

## 部署

```bash
cp .env.example .env      # 填写 MASTER_KEY、SESSION_SECRET、POSTGRES_PASSWORD、ADMIN_BOOTSTRAP_*、上游密钥
docker compose up -d --build
```

`.env` 中 `COMPOSE_PROFILES` 决定部署形态：

| 取值 | 内容 |
|---|---|
| `single` | 单个网关实例 + Postgres + Redis，端口 8080 |
| `ha` | 两个网关实例（gate-1 / gate-2）+ nginx 负载均衡（8080），共享 Postgres 与 Redis |
| `ha,monitoring` | 在 ha 基础上加 Prometheus（9090），已加载告警规则 |

- 容器启动时自动执行数据库迁移（Alembic，Postgres 上有 advisory lock，多实例同时启动也安全）；v0.1 的数据库会被识别并原地升级。
- 首个管理员由 `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD` 创建（仅当还没有管理员时），之后可在后台添加更多管理员。
- 生产请在 nginx 前加 TLS，并设置 `COOKIE_SECURE=1`。单实例默认不信任代理头；ha 模式已自动开启。若在 nginx 前再加一层代理，需让外层也覆盖这两个头。
- `/metrics` 在 nginx 上默认对外屏蔽，Prometheus 直接抓取各实例。

手动迁移：`python -m autollm_admin.migrate`。

## 主要环境变量

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` / `REDIS_URL` | 数据库与 Redis；不配 Redis 时退化为单进程内存状态（仅开发用） |
| `MASTER_KEY` | 上游密钥加密主密钥 |
| `SESSION_SECRET` | 登录态签名密钥，≥32 字符 |
| `ENV` | `production` 时启用安全检查 |
| `ENABLE_MOCK_PAYMENT` | 模拟支付，仅测试环境 |
| `DEFAULT_KEY_RPM` / `SIGNUP_RATE` / `LOGIN_RATE` | 限流 |
| `BREAKER_THRESHOLD` / `BREAKER_COOLDOWN` | 熔断阈值与冷却秒数 |
| `ALERT_INTERVAL` | 告警评估间隔（秒） |

完整列表见 `.env.example`。

## 开发

```bash
pip install -r requirements-dev.lock && pip install -e .
pytest                                  # 设置 TEST_DATABASE_URL 可额外跑 Postgres 并发测试
cd web && npm ci && npm run typecheck && npm run build
```

辅助脚本（`scripts/`）：`fake_upstream.py` 假上游、`seed_demo.py` 演示数据、`loadtest.py` 压测与故障切换探测、`alert_receiver.py` 本地 Webhook 接收器、`screenshots.py` 页面截图。

验收记录见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。

## 已知限制

- 熔断状态按进程独立统计（各实例各自判断），未在 Redis 共享
- 真实支付渠道（微信/支付宝/Stripe）仍为占位，需对接商户号
- Postgres / Redis / nginx 仍为单点，生产需换托管或主从方案
- 监控页 P50/P95 为直方图分桶上界，属近似值
