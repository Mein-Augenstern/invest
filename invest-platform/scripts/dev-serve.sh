#!/usr/bin/env bash
# 本机 dev 启动：从 gitignore 的 .env.dev 注入密钥/连接串，起 star 鉴权 + LAN 两个端口。
# .env.dev 模板（本文件不落任何真实值）：
#   INVEST_JWT_SECRET=<40 字节随机串——注意 ≥48 字节会把 star 侧切到 HS384 导致 invest 401>
#   INVEST_DB_URL=mysql://user:pass@127.0.0.1:3307/invest_dev
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
nohup .venv/bin/python3 -m invest serve --lan --port 8792 >> logs/serve-8792.log 2>&1 &
echo "serve --lan       :8792 (pid $!)"
