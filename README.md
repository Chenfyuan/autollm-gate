# AutoLLM Gate

OpenAI / Anthropic 双协议兼容的 **智能 LLM 路由网关**。客户端只需把 `base_url` 指向 AutoLLM Gate，`model` 填 `auto`，网关按请求特征与策略自动挑选最合适的模型，失败自动降级，并按 token 计量计费。

> 本项目为独立从零实现，仅参考同类产品的公开行为描述，不包含任何第三方代码或内部评分数据。

## 功能

| 能力 | 说明 |
|---|---|
| OpenAI 兼容 | `POST /v1/chat/completions`（含流式、工具调用）、`GET /v1/models` |
| Anthropic 兼容 | `POST /v1/messages`（含流式、tool_use）、`/v1/messages/count_tokens`，Claude Code 改 base URL 即可用 |
| 智能路由 | `auto`（默认 = `auto:cost_optimized`）、`auto:balanced`、`auto:quality_first`、`auto:latency_critical` |
| 请求分类 | chat / coding / reasoning / long_context，按任务选用对应评分维度，并过滤上下文不够的模型 |
| 评分配置 | `core/autollm_gate/scoring.yaml`，可编辑；分数参考 LMArena、Artificial Analysis 公开榜单与厂商公开定价 |
| 会话粘性 | `X-Session-Id` 头；没有时自动识别 Claude Code `metadata.user_id` 中的 session、Codex `session_id`/`prompt_cache_key`，最后用对话前缀指纹 |
| 上游 | OpenAI、Anthropic、Google Gemini、DeepSeek 直连 + 自部署开源模型（vLLM/Ollama 等 OpenAI 兼容端点） |
| 降级重试 | 首包前上游 5xx/429/超时/鉴权失败时，按排名顺序切换下一个模型（默认最多 3 次） |
| 可观测 | 响应头 `X-Router-Model` / `X-Router-Provider` / `X-Router-Strategy` / `X-Router-Task` / `X-Router-Reason` / `X-Router-Attempts` |
| 多租户 | 租户、API Key（只存 SHA-256）、启停、吊销 |
| 上游 Key | ① 平台统一 Key（后台填入即启用，按用量扣余额，可配加价）② 租户自带 Key（BYOK，优先于平台 Key）③ 自部署模型。全部 Fernet 加密存储 |
| 计费 | 预付余额（微美元整数）、按 token 计量、月度 token 额度、充值记录、支付渠道占位接口 |
| 管理后台 | `/admin`：租户、发 Key、充值、BYOK、平台 Key、用量统计、充值记录 |

## 目录结构

```
core/autollm_gate/     开源内核：路由、协议转换、上游适配、会话粘性（不依赖数据库）
admin/autollm_admin/   商业层：多租户、计费、余额、充值、管理后台（可独立闭源）
tests/                 单元测试（全部使用 mock 上游，不发真实请求）
```

内核通过 `GatewayHooks`（鉴权 / 额度检查 / 用量记录）扩展，商业层实现 `BillingHooks` 注入，两部分目录完全分离。

## 快速部署（Docker Compose）

```bash
cp .env.example .env      # 填写 ROUTER_MASTER_KEY / ADMIN_TOKEN / POSTGRES_PASSWORD
docker compose up -d --build
```

镜像名 `autollm-gate:latest`，服务监听 `8080`。然后：

```bash
# 1. 配置平台上游 Key（填入即启用）
curl -X PUT localhost:8080/admin/api/platform/upstream -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"provider":"openai","api_key":"sk-..."}'
# 2. 建租户 → 发 Key → 充值
curl -X POST localhost:8080/admin/api/tenants -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' -d '{"name":"acme"}'
curl -X POST localhost:8080/admin/api/tenants/<tid>/keys -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' -d '{}'
curl -X POST localhost:8080/admin/api/tenants/<tid>/topups -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' -d '{"amount_usd":10}'
# 3. 调用
curl localhost:8080/v1/chat/completions -H "Authorization: Bearer sk-lr-..." -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"你好"}]}' -i
```

也可以直接打开 `http://localhost:8080/admin` 用网页操作。

**纯开源内核（单租户、无数据库）**：`APP=autollm_gate.main:app`，上游 Key 用环境变量 `OPENAI_API_KEY` 等，可选 `ROUTER_API_KEY` 做访问保护。

### 客户端接入

- OpenAI SDK：`OpenAI(base_url="http://host:8080/v1", api_key="sk-lr-...")`，`model="auto"`
- Claude Code：`export ANTHROPIC_BASE_URL=http://host:8080 ANTHROPIC_AUTH_TOKEN=sk-lr-... ANTHROPIC_MODEL=auto`
- Codex CLI：在配置中把 provider 的 `base_url` 设为 `http://host:8080/v1`，`model = "auto"`（使用 chat completions 接口）

## 配置

| 环境变量 | 说明 |
|---|---|
| `DATABASE_URL` | 默认 `sqlite:///./autollm_gate.db`；生产用 `postgresql+psycopg2://...` |
| `ROUTER_MASTER_KEY` | 上游 Key 加密主密钥（必填，丢失后已存 Key 无法解密） |
| `ADMIN_TOKEN` | 管理 API 令牌 |
| `PLATFORM_MARKUP_PCT` | 平台 Key 加价百分比，默认 20；租户 `markup_pct` 可覆盖 |
| `BYOK_FEE_PER_REQUEST_USD` / `BYOK_FEE_PER_1K_TOKENS_USD` | BYOK 服务费，默认 0 |
| `SELFHOSTED_BASE_URL` | 自部署模型端点；在后台以 provider=`selfhosted` 填其 token 即启用，按 scoring.yaml 中的售价计费 |
| `ROUTER_SCORING_FILE` | 自定义评分 YAML 路径 |
| `ENV` | `production`（镜像默认）时启用安全检查 |
| `ENABLE_MOCK_PAYMENT` | 1 = 启用模拟支付渠道（仅开发；`ENV=production` 时设为 1 会拒绝启动） |

计费规则：平台 Key = 上游公开价 ×(1+加价%)；自部署 = YAML 售价；BYOK = 服务费。余额 ≤ 0 时只能使用租户自带 Key。

## 合规说明

将平台自有的上游 API Key 以按量计费的方式提供给第三方使用（转售），可能违反部分模型厂商的服务条款。商业化运营前请确认已取得相应授权（如企业协议、云厂商 Azure OpenAI / AWS Bedrock / Google Vertex 的转售许可），或优先采用「租户自带 Key」与「自部署开源权重模型（注意模型许可证）」模式。本项目不对使用方式作合规担保。

## 依赖锁定

`requirements.lock`（运行时）与 `requirements-dev.lock`（含测试）由 uv 针对 Python 3.11 生成并带哈希，Docker 构建按锁文件安装。升级依赖：

```bash
uv pip compile pyproject.toml --python-version 3.11 --generate-hashes -o requirements.lock
uv pip compile pyproject.toml --extra dev --python-version 3.11 --generate-hashes -o requirements-dev.lock
```

## 测试

```bash
python -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-dev.lock && .venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
```

## 商业化路线图

1. **v0.1（当前）**：双协议网关、四种策略、会话粘性、三种上游 Key 模式、余额计费、简易后台
2. **v0.2**：接入真实支付（Stripe / 支付宝 / 微信，实现 `PaymentChannel`）、租户自助控制台与注册、邮件通知、发票
3. **v0.3**：Redis 共享会话与限流（多实例）、按 Key 的 RPM/TPM 限流、异步 DB、Prometheus 指标
4. **v0.4**：基于真实反馈的路由学习（成功率、延迟、用户评分自动调权）、语义缓存、Prompt 缓存计费
5. **v1.0**：企业版（SSO、审计日志、私有化部署、SLA）、团队/子账号、预算告警；内核开源获客，计费后台闭源/SaaS 变现
