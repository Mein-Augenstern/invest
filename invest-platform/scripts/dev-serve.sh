#!/usr/bin/env bash
# 本机 dev 启动：从 gitignore 的 .env.dev 注入密钥/连接串，起 star 鉴权 + LAN 两个端口。
# .env.dev 模板（本文件不落任何真实值）：
#   INVEST_JWT_SECRET=<40 字节随机串——注意 ≥48 字节会把 star 侧切到 HS384 导致 invest 401>
#   INVEST_DB_URL=mysql://user:pass@127.0.0.1:3307/invest_dev
#   INVEST_LAN_TOKEN=<固定 LAN 令牌——不设则 --lan 每次启动随机生成，体验版直连会 401；
#                     值须与 miniapp/.env.production.local 的 VITE_INVEST_PUBLIC_TOKEN 一致>
#   （缺省 INVEST_DB_URL 则回落 SQLite data/invest.db）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.dev ]; then
  set -a; source .env.dev; set +a
fi

# GLM Key（S2 设置页写入的 config/glm.local.env）：启动时一并注入，
# 免去重启后需在设置页重存一次才生效的缺口
if [ -f config/glm.local.env ]; then
  set -a; source config/glm.local.env; set +a
fi

: "${INVEST_JWT_SECRET:?缺 INVEST_JWT_SECRET（写入 invest-platform/.env.dev，见 scripts/dev-serve.sh 头部模板）}"

mkdir -p logs
nohup .venv/bin/python3 -m invest serve --auth star --port 8790 >> logs/serve-8790.log 2>&1 &
echo "serve --auth star :8790 (pid $!)"
# 固定 LAN 令牌（体验版直连）：不传 --token 时 --lan 每次随机生成令牌，
# 已构建进小程序的固定令牌会在 invest 重启后失配（G2 调通时踩到，已修）。
# "${arr[@]+...}" 惯用法：macOS bash 3.2 在 set -u 下空数组展开报 unbound
LAN_TOKEN_ARG=()
if [ -n "${INVEST_LAN_TOKEN:-}" ]; then
  LAN_TOKEN_ARG=(--token "$INVEST_LAN_TOKEN")
fi
nohup .venv/bin/python3 -m invest serve --lan --port 8792 ${LAN_TOKEN_ARG[@]+"${LAN_TOKEN_ARG[@]}"} >> logs/serve-8792.log 2>&1 &
echo "serve --lan       :8792 (pid $!)"
