#!/bin/sh
# 一键演示（只用假上游，不花钱）：管理员登录 → 配置假 OpenAI Key → 建租户 → 充值 1 美元 → 建 API Key → 调一次对话接口。
# 用法（在 .env 所在目录）：sh scripts/quickstart-demo.sh   可用 GATE=http://localhost:18080 指定地址
set -e
GATE="${GATE:-http://localhost:${GATE_PORT:-8080}}"
EMAIL=$(grep ^ADMIN_BOOTSTRAP_EMAIL= .env | cut -d= -f2-)
PASS=$(grep ^ADMIN_BOOTSTRAP_PASSWORD= .env | cut -d= -f2-)
JAR=$(mktemp); trap 'rm -f "$JAR"' EXIT
# 不依赖 python/jq：从 JSON 里取字符串字段
j() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p"; }
echo "1) 健康检查：$(curl -fsS "$GATE/healthz")"
curl -fsS -c "$JAR" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" "$GATE/api/admin/auth/login" >/dev/null
echo "2) 管理员登录成功：$EMAIL"
curl -fsS -b "$JAR" -H "X-Requested-With: autollm" -X PUT -H 'content-type: application/json' -d '{"provider":"openai","api_key":"sk-fake-local-demo"}' "$GATE/api/admin/upstreams" >/dev/null
echo "3) 已配置假 OpenAI 上游 Key"
TID=$(curl -fsS -b "$JAR" -H "X-Requested-With: autollm" -H 'content-type: application/json' -d '{"name":"本地演示租户"}' "$GATE/api/admin/tenants" | j id)
curl -fsS -b "$JAR" -H "X-Requested-With: autollm" -H 'content-type: application/json' -d '{"amount_usd":1,"note":"本地演示"}' "$GATE/api/admin/tenants/$TID/topups" >/dev/null
KEY=$(curl -fsS -b "$JAR" -H "X-Requested-With: autollm" -H 'content-type: application/json' -d '{"name":"演示"}' "$GATE/api/admin/tenants/$TID/keys" | j api_key)
echo "4) 已创建租户（余额 1 美元）和 API Key：${KEY%"${KEY#??????????}"}…"
echo "5) 调用 /v1/chat/completions："
curl -fsS "$GATE/v1/chat/completions" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"你好"}]}'
echo
echo "完成。可以打开 $GATE/admin 查看请求日志和扣费。"
