# ---------- 前端构建 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 运行镜像 ----------
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ENV=production STATIC_DIR=/app/static PORT=8080
# 先按锁文件（含哈希）安装依赖，再无依赖安装本项目，保证构建可复现
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY core ./core
COPY admin ./admin
RUN pip install --no-cache-dir --no-deps . && useradd -r -u 10001 app
COPY --from=web /web/dist /app/static
COPY deploy/entrypoint.sh /entrypoint.sh
USER app
# APP=autollm_admin.main:app（托管版）或 autollm_gate.main:app（纯开源内核）
ENV APP=autollm_admin.main:app WORKERS=2
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz',timeout=2)"
ENTRYPOINT ["sh", "/entrypoint.sh"]
