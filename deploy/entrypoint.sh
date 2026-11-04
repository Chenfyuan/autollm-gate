#!/bin/sh
set -e
# 托管版启动前执行数据库迁移（多副本并发启动时由 advisory lock 串行化）
if [ "$APP" = "autollm_admin.main:app" ] && [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  python -m autollm_admin.migrate
fi
exec uvicorn "$APP" --host 0.0.0.0 --port "${PORT:-8080}" --workers "${WORKERS:-2}" --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" --no-access-log
