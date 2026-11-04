#!/bin/sh
# 生成带随机密钥的 .env（不会覆盖已有 .env）。用法：sh scripts/gen-env.sh [模板文件]
set -e
TPL="${1:-quickstart.env.example}"
[ -f "$TPL" ] || TPL="$(dirname "$0")/../quickstart.env.example"
if [ -f .env ]; then echo ".env 已存在，未覆盖。要重新生成请先删除 .env"; exit 1; fi
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"; }
FERNET=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')
PW=$(rnd 16)
sed -e "s|^ROUTER_MASTER_KEY=.*|ROUTER_MASTER_KEY=$FERNET|" \
    -e "s|^SESSION_SECRET=.*|SESSION_SECRET=$(rnd 48)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rnd 24)|" \
    -e "s|^ADMIN_BOOTSTRAP_PASSWORD=.*|ADMIN_BOOTSTRAP_PASSWORD=$PW|" "$TPL" > .env
chmod 600 .env
echo "已生成 .env"
echo "管理员邮箱：$(grep ^ADMIN_BOOTSTRAP_EMAIL= .env | cut -d= -f2)"
echo "管理员密码：$PW   （请记下来，也可以随时在 .env 里查看）"
