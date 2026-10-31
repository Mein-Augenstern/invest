#!/usr/bin/env bash
# 拉起 invest 公网隧道（frpc Docker 容器，host 网络）。
# 前置：invest-platform/.env.dev 提供 INVEST_FRP_TOKEN（= ECS frps.toml 的 auth.token，
#       真实值不入库）；invest --lan :8792 已由 dev-serve.sh 拉起。
# 验证：curl -H "Host: 47.92.235.34" http://47.92.235.34:8080/api/invest/ping
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.dev ]; then
  set -a; source .env.dev; set +a
fi
: "${INVEST_FRP_TOKEN:?缺 INVEST_FRP_TOKEN（写入 invest-platform/.env.dev，值 = ECS frps.toml 的 auth.token）}"

# 先健康预检本机 8792（隧道通了也只是转发到空端口，先确认源活着）
if ! curl -s -m 3 -o /dev/null http://127.0.0.1:8792/api/invest/ping; then
  echo "警告：本机 :8792 不可达——先跑 ./scripts/dev-serve.sh 再拉隧道" >&2
fi

docker rm -f invest-frpc 2>/dev/null || true
docker run -d --name invest-frpc --network host --restart unless-stopped \
  -v "$(pwd)/scripts/frpc.toml:/etc/frp/frpc.toml:ro" \
  -e INVEST_FRP_TOKEN \
  snowdreamtech/frpc:latest

sleep 3
docker logs invest-frpc 2>&1 | tail -5
echo ""
echo "隧道状态查询：docker logs -f invest-frpc"
echo "公网验证：curl -H 'Host: 47.92.235.34' http://47.92.235.34:8080/api/invest/ping"
