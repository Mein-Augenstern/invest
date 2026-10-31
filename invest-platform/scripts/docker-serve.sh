#!/usr/bin/env bash
# invest 容器化常驻部署（G2 收口：替代 nohup dev-serve——后者时活时死且 launchd 被
# macOS TCC 拦"Operation not permitted"；容器 --restart 自愈，与 star 家族基建同形态）。
#
# 两个容器（同 docker_default 网络，与 star-mysql/gateway 直连）：
#   star-invest-star :8790  star JWT 鉴权（star 网关转发 /api/invest/** 的上游）
#   star-invest-lan  :8792  固定令牌鉴权（公网隧道 frpc 的后端，小程序体验版直连）
#
# 前置：镜像已构建（docker build -t star-site/platform-invest:latest .）；
#       .env.dev 提供 INVEST_JWT_SECRET / INVEST_LAN_TOKEN / INVEST_DB_URL（真实值不入库）。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.dev ]; then
  set -a; source .env.dev; set +a
fi
: "${INVEST_JWT_SECRET:?缺 INVEST_JWT_SECRET}"
: "${INVEST_LAN_TOKEN:?缺 INVEST_LAN_TOKEN（体验版直连令牌，与 miniapp .env.production.local 一致）}"

# 容器网络视角的 DB URL：.env.dev 里的 127.0.0.1:3307 换 star-mysql:3306（同网容器名直连）
DB_URL="${INVEST_DB_URL:-}"
CONTAINER_DB_URL="${DB_URL//127.0.0.1:3307/star-mysql:3306}"

NET="docker_default"
IMAGE="star-site/platform-invest:latest"
DATA_DIR="$(pwd)/data"
mkdir -p "$DATA_DIR" logs

# GLM Key（S2 设置页写入的 config/glm.local.env）——运行期不注入（设置页/库内已有），
# 与原 dev-serve 行为差异：容器重建后 config/ 内的 key 不丢（挂载 config/ 只读）

for C in star-invest-star star-invest-lan; do docker rm -f "$C" 2>/dev/null || true; done

# ① star 形态（网关上游）：JWT 鉴权 + gmt 数据目录挂载
docker run -d --name star-invest-star --network "$NET" --restart unless-stopped \
  -p 127.0.0.1:8790:8790 \
  -e INVEST_AUTH_MODE=star \
  -e INVEST_JWT_SECRET \
  -e INVEST_DB_URL="$CONTAINER_DB_URL" \
  -e INVEST_DATA_DIR=/data \
  -v "$DATA_DIR:/data" \
  -v "$(pwd)/config:/app/config:ro" \
  "$IMAGE" >> logs/docker-serve.log 2>&1
echo "star-invest-star :8790 (star JWT, 网关上游)"

# ② LAN 形态（公网隧道后端）：固定令牌（体验版直连；--lan 的随机令牌已踩坑，固定值）。
# CMD 覆盖：镜像默认 uvicorn :8790（star 形态），此处改 --port 8792
docker run -d --name star-invest-lan --network "$NET" --restart unless-stopped \
  -p 127.0.0.1:8792:8792 \
  -e INVEST_AUTH_MODE=token \
  -e INVEST_MP_TOKEN="$INVEST_LAN_TOKEN" \
  -e INVEST_DB_URL="$CONTAINER_DB_URL" \
  -e INVEST_DATA_DIR=/data \
  -v "$DATA_DIR:/data" \
  -v "$(pwd)/config:/app/config:ro" \
  "$IMAGE" \
  uv run --no-dev uvicorn invest.webapp.main:app --host 0.0.0.0 --port 8792 >> logs/docker-serve.log 2>&1
echo "star-invest-lan  :8792 (固定令牌, 隧道后端)"

echo "验证：docker logs star-invest-star / star-invest-lan"
