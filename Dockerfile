FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ENV=production
# 先按锁文件（含哈希）安装依赖，再无依赖安装本项目，保证构建可复现
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY core ./core
COPY admin ./admin
RUN pip install --no-cache-dir --no-deps .
# APP=autollm_admin.main:app（托管版）或 autollm_gate.main:app（纯开源内核）
ENV APP=autollm_admin.main:app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn $APP --host 0.0.0.0 --port 8080 --proxy-headers"]
