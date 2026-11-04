# 部署与配置详解

> 版权所有（All rights reserved）。源码仅供查看，未经书面许可不得使用、复制、修改或分发，详见 [LICENSE](../LICENSE)。

## 一、在自己电脑上一键体验（不懂技术也能照做）

整个过程大约 10 分钟，不需要写代码，也不会产生任何费用：默认接的是「假上游」，不会调用真实模型。

### 第 1 步：安装 Docker Desktop

1. 打开 <https://www.docker.com/products/docker-desktop/> 下载安装。
   - Mac：先点左上角苹果图标 →「关于本机」，看「芯片」一栏。写着 Apple M1/M2/M3/M4 的选 **Apple Silicon** 版，写着 Intel 的选 **Intel** 版。
   - Windows：选 Windows 版，安装时保持勾选 WSL 2。
2. 安装后打开 Docker Desktop，等左下角显示绿色的 **Engine running**。

### 第 2 步：下载 4 个文件

新建一个文件夹（比如桌面上的 `autollm`），打开「终端」（Mac：启动台搜索“终端”；Windows：开始菜单搜索 “PowerShell”），依次输入：

```bash
cd ~/Desktop && mkdir -p autollm && cd autollm
curl -fsSLO https://raw.githubusercontent.com/Chenfyuan/autollm-gate/main/docker-compose.quickstart.yml
curl -fsSLO https://raw.githubusercontent.com/Chenfyuan/autollm-gate/main/quickstart.env.example
curl -fsSL  https://raw.githubusercontent.com/Chenfyuan/autollm-gate/main/scripts/gen-env.sh -o gen-env.sh
curl -fsSL  https://raw.githubusercontent.com/Chenfyuan/autollm-gate/main/scripts/quickstart-demo.sh -o quickstart-demo.sh
```

### 第 3 步：生成配置文件 .env

```bash
sh gen-env.sh
```

它会自动生成随机密码和密钥，并在屏幕上打印**管理员邮箱和密码**，请记下来（忘了可以打开 `.env` 文件查看 `ADMIN_BOOTSTRAP_PASSWORD`）。

> Windows 没有 `sh` 时：把 `quickstart.env.example` 复制一份改名为 `.env`，用记事本把所有 `CHANGE_ME` 换成你自己的长随机字符串；`ROUTER_MASTER_KEY` 必须是 44 位的 Fernet 密钥，可在 <https://fernetkeygen.com> 之类的工具生成，或在 Docker 里运行 `docker run --rm python:3.11-slim python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`。

### 第 4 步：一条命令启动

```bash
docker compose -f docker-compose.quickstart.yml up -d
```

第一次会下载镜像，需要几分钟。数据库表会自动创建，不用手动操作。看到 4 个服务都是 `Started` / `Healthy` 就好了。

### 第 5 步：打开网页

| 地址 | 用途 |
|---|---|
| <http://localhost:8080/admin> | 运营后台（用第 3 步的管理员邮箱和密码登录） |
| <http://localhost:8080/console> | 客户自助控制台（客户在 /signup 注册后登录） |
| <http://localhost:8080/healthz> | 健康检查，显示 `ok` 说明服务正常 |

### 第 6 步：发一次测试请求（用假上游，不花钱）

**最省事的办法**：运行演示脚本，它会自动完成登录、配置假上游 Key、建租户、充值 1 美元、建 API Key，再调一次对话接口：

```bash
sh quickstart-demo.sh
```

最后一行能看到 `"content":"假上游回复：gpt-4o-mini"` 就说明整条链路（鉴权 → 路由 → 计费 → 上游）都通了。

**想在网页上自己点一遍**：

1. 后台「上游密钥」→ OpenAI → 随便填一个 `sk-fake-12345678` 保存（本地配置里 OpenAI 已指向假上游）。
2. 后台「租户」→ 新建租户 → 进入租户详情 → 手工充值，比如 1 美元。
3. 在租户详情里「创建 Key」，复制弹出的 `sk-…`（只显示一次）。
4. 在终端里发请求（把 `你的Key` 换掉）：

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer 你的Key" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"你好"}]}'
```

**改用真实模型**：打开 `.env`，删掉 `OPENAI_BASE_URL=...` 这一行，执行 `docker compose -f docker-compose.quickstart.yml up -d` 重启，再到后台「上游密钥」填入真实的 OpenAI / Anthropic / DeepSeek 等 Key。真实调用会产生上游费用。

### 常用命令

| 想做什么 | 命令 |
|---|---|
| 停止（数据保留） | `docker compose -f docker-compose.quickstart.yml down` |
| 再次启动 | `docker compose -f docker-compose.quickstart.yml up -d` |
| 升级到最新版 | `docker compose -f docker-compose.quickstart.yml pull && docker compose -f docker-compose.quickstart.yml up -d` |
| 查看日志 | `docker compose -f docker-compose.quickstart.yml logs -f gate` |
| **清空所有数据从头来过** | `docker compose -f docker-compose.quickstart.yml down -v`（不可恢复） |

在源码目录里也可以用 `make up` / `make down` / `make upgrade` / `make reset`。

### 常见问题

- **想让同一局域网的其他设备（手机、另一台电脑）访问**：快速体验默认只监听本机 `127.0.0.1`，局域网里的其他设备访问不到，这是为了避免管理后台被同网络的人看到。确实需要时，在 `.env` 里加一行 `GATE_BIND=0.0.0.0`，执行 `docker compose -f docker-compose.quickstart.yml up -d` 重启，其他设备用 `http://<本机局域网 IP>:8080` 访问。用完建议改回 `127.0.0.1`，并确保管理员密码足够强。
- **提示端口 8080 被占用**（`port is already allocated`）：打开 `.env`，把 `GATE_PORT=8080` 改成 `18080`，重新启动后访问 <http://localhost:18080>；运行演示脚本时用 `GATE=http://localhost:18080 sh quickstart-demo.sh`。
- **Apple 芯片 Mac 能用吗**：能。镜像同时提供 Intel/AMD（amd64）和 ARM（arm64）版本，Docker 会自动下载适合你电脑的那个，不需要 Rosetta。
- **数据存在哪**：在 Docker 数据卷 `autollm_pgdata`（数据库）和 `autollm_redisdata`（缓存）里，可在 Docker Desktop 的「Volumes」页面看到。`down` 不会删除它们，`down -v` 会。
- **后台登录不上**：确认 `.env` 里 `COOKIE_SECURE=0`（本地是 http，必须为 0）；如果改过 `ADMIN_BOOTSTRAP_PASSWORD`，它只在第一次启动时生效，可执行 `down -v` 清空后重新启动。
- **想看是哪里出错**：`docker compose -f docker-compose.quickstart.yml logs gate`。

### 自己构建镜像（开发者）

```bash
git clone https://github.com/Chenfyuan/autollm-gate.git && cd autollm-gate
sh scripts/gen-env.sh
docker compose -f docker-compose.quickstart.yml build        # 本机架构，等同 make images
docker compose -f docker-compose.quickstart.yml up -d
docker buildx bake                                           # amd64 + arm64 多架构，等同 make images-multiarch
```

公开镜像由 GitHub Actions（`.github/workflows/images.yml`）在 main 分支代码变更、打 `v*` 标签或手动触发时自动构建，推送到 `ghcr.io/chenfyuan/autollm-gate-gateway`，标签有 `latest`、`sha-<提交号>` 和版本号。一个镜像同时包含网关、运营后台和客户控制台。公开镜像只使用公开默认内核，不含私有核心插件。

## 二、部署到甲骨文云（Oracle Cloud）新加坡 ARM 服务器

适合正式对外服务的起步方案。新加坡区域不需要 ICP 备案，连海外模型延迟低。账号注册和绑卡需要你本人完成；生产环境建议把账号升级为按量付费（仍享受免费额度，但实例不会被当作闲置回收）。

1. **创建实例**：区域选 `ap-singapore-1`，镜像选 Ubuntu 22.04/24.04，形状选 `VM.Standard.A1.Flex`（ARM，例如 2 核 12G 或 4 核 24G）。「SSH 密钥」上传你自己的公钥（不要用密码登录）。
2. **只开放 80 和 443**：在 VCN 安全列表 / 网络安全组里只放行 TCP 80、443；22 端口只允许你自己的 IP。**不要**放行 5432（Postgres）、6379（Redis）、8080。Ubuntu 镜像自带 iptables 规则，还需要在服务器上放行 80/443：
   ```bash
   sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save
   ```
3. **安装 Docker**：
   ```bash
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # 重新登录后生效
   ```
4. **启动服务**：按上面第 2、3 步下载文件并生成 `.env`，然后修改 `.env`：
   - 删掉 `OPENAI_BASE_URL=...`（使用真实上游）；
   - `COOKIE_SECURE=1`（下面会配 HTTPS）；
   - `ADMIN_BOOTSTRAP_EMAIL` 改成你自己的邮箱。

   为了让网关只监听本机、不直接暴露 8080，在同目录新建 `docker-compose.override.yml`：
   ```yaml
   services:
     gate:
       ports: !override ["127.0.0.1:8080:8080"]
   ```
   然后 `docker compose -f docker-compose.quickstart.yml -f docker-compose.override.yml up -d`。数据库和 Redis 在 compose 里本来就没有映射端口，公网访问不到。
5. **配置 HTTPS（二选一）**
   - **Caddy（推荐，自动申请和续期证书）**：先把域名的 A 记录指向服务器公网 IP，然后：
     ```bash
     sudo apt install -y caddy
     echo 'api.你的域名.com {
         reverse_proxy 127.0.0.1:8080
     }' | sudo tee /etc/caddy/Caddyfile && sudo systemctl reload caddy
     ```
     同时在 override 文件的 gate 下加 `environment: {TRUST_PROXY: "1"}`，以便记录真实客户端 IP。
   - **nginx + certbot**：`sudo apt install -y nginx certbot python3-certbot-nginx`，新建站点把 `proxy_pass http://127.0.0.1:8080;` 并带上 `proxy_set_header X-Forwarded-For $remote_addr; proxy_set_header X-Forwarded-Proto $scheme; proxy_buffering off;`（流式输出需要），再执行 `sudo certbot --nginx -d api.你的域名.com`。
6. **备份**：每天导出数据库并上传到对象存储，例如
   `docker compose -f docker-compose.quickstart.yml exec -T db pg_dump -U autollm autollm | gzip > backup-$(date +%F).sql.gz`。
7. **密钥安全**：`.env` 只放在服务器上（`chmod 600`），不要提交到 git，也不要写进镜像。`ROUTER_MASTER_KEY` 丢失后已保存的上游 Key 无法解密，请离线另存一份。

## 三、从源码部署（多实例 / 监控）


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

## 私有核心插件（可选）

路由评分与计价规则通过插件接口加载（`autollm_gate/plugins.py`）。不安装插件时使用公开仓库自带的默认实现，功能完整可运行。

- 安装方式：私有包注册 entry point `autollm_gate.core`，安装后自动加载；或设置 `AUTOLLM_CORE_PLUGIN=模块:对象` 指定；设为 `off` 强制使用默认实现。
- 加载失败会记录错误并回退默认实现，`/healthz` 返回的 `core` 字段显示当前生效的实现。
- Docker 构建时可选安装（凭据只经 BuildKit secret 传入，不写入镜像层、不出现在构建日志）：

```bash
CORE_TOKEN=<只读访问令牌> docker build \
  --build-arg CORE_REPO=<owner>/<private-repo> \
  --secret id=core_token,env=CORE_TOKEN -t autollm-gate .
```

CI 中把令牌存为仓库 Secret，切勿写入代码、`.env` 示例或工作流明文。


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

