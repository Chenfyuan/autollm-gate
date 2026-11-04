# syntax=docker/dockerfile:1
# ---------- 前端构建 ----------
# 前端产物与 CPU 架构无关，固定在构建机原生架构上构建，多架构构建时更快
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 运行镜像 ----------
FROM python:3.11-slim
LABEL org.opencontainers.image.source=https://github.com/Chenfyuan/autollm-gate \
      org.opencontainers.image.description="AutoLLM Gate 网关 + 管理后台 + 租户门户（单镜像）" \
      org.opencontainers.image.licenses="LicenseRef-AllRightsReserved"
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ENV=production STATIC_DIR=/app/static PORT=8080
# 先按锁文件（含哈希）安装依赖，再无依赖安装本项目，保证构建可复现
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY core ./core
COPY admin ./admin
RUN pip install --no-cache-dir --no-deps . && useradd -r -u 10001 app
# ---------- 可选：私有核心插件 ----------
# 不提供时使用公开默认实现。凭据只通过 BuildKit secret 传入，不会进入任何镜像层：
#   docker build --build-arg CORE_REPO=Chenfyuan/autollm-gate-core --secret id=core_token,env=CORE_TOKEN .
ARG CORE_REPO=""
ARG CORE_REF=main
RUN --mount=type=secret,id=core_token,required=false \
    if [ -n "$CORE_REPO" ] && [ -s /run/secrets/core_token ]; then \
      python -c "import os,urllib.request as u;r=u.Request(f'https://api.github.com/repos/{os.environ[\"CORE_REPO\"]}/tarball/{os.environ[\"CORE_REF\"]}',headers={'Authorization':'Bearer '+open('/run/secrets/core_token').read().strip()});open('/tmp/core.tgz','wb').write(u.urlopen(r).read())" \
      && pip install --no-cache-dir --no-deps /tmp/core.tgz && rm -f /tmp/core.tgz; \
    else echo "private core not provided, using default implementation"; fi
COPY --from=web /web/dist /app/static
COPY deploy/entrypoint.sh /entrypoint.sh
# 本地体验用的假上游（不发任何真实请求），quickstart 中以独立容器运行
COPY scripts/fake_upstream.py /app/scripts/fake_upstream.py
USER app
# APP=autollm_admin.main:app（托管版）或 autollm_gate.main:app（纯开源内核）
ENV APP=autollm_admin.main:app WORKERS=2
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz',timeout=2)"
ENTRYPOINT ["sh", "/entrypoint.sh"]
