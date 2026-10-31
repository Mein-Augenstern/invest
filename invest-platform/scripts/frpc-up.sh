#!/usr/bin/env bash
# 拉起 invest 公网隧道（frpc Docker 容器，docker_default 网络直连 invest 容器）。
# 前置：invest-platform/.env.dev 提供 INVEST_FRP_TOKEN（= ECS frps.toml 的 auth.token，
#       真实值不入库）；star-invest-lan :8792 已由 docker-serve.sh 拉起。
# 实现：token 含 $ ! @ 等特殊字符，frp {$VAR} 模板展开链路（shell→docker -e→frp）
# 各环节语义差异难排查（G2 实调踩坑：shell 端值正确但 frp 报 token mismatch）——
# 改为启动时 sed 渲染到 0600 临时文件挂载，明文不落仓库。
# 验证：curl http://47.92.235.34:8080/api/invest/ping
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.dev ]; then
  set -a; source .env.dev; set +a
fi
: "${INVEST_FRP_TOKEN:?缺 INVEST_FRP_TOKEN（写入 invest-platform/.env.dev，值 = ECS frps.toml 的 auth.token）}"

# 健康预检（容器对容器：frpc 与 invest 同 docker_default 网络，按容器名直连）
if ! docker ps --format '{{.Names}}' | grep -q '^star-invest-lan$'; then
  echo "警告：star-invest-lan 容器不在运行——先跑 ./scripts/docker-serve.sh 再拉隧道" >&2
fi

# 渲染配置（token 单行替换；分隔符 | 防 token 内 / 歧义；0600 临时文件）
RENDERED=$(mktemp /tmp/invest-frpc.XXXXXX.toml)
chmod 600 "$RENDERED"
sed "s|{\$INVEST_FRP_TOKEN}|${INVEST_FRP_TOKEN}|" scripts/frpc.toml > "$RENDERED"
trap 'rm -f "$RENDERED"' EXIT

docker rm -f invest-frpc 2>/dev/null || true
# 镜像版本固定 0.64.0 与 ECS frps 严格同版（G2 实调踩坑：跨版本控制连接能登录、
# http work 连接转发 EOF——frp 官方不保证跨版本兼容）。
# 网络演进（三连踩的最终形态）：--network host 的 localIP 无论 127.0.0.1（Docker VM
# 回环）还是 host.docker.internal（host-gateway 桥接）都是间接层——干脆同
# docker_default 网络容器对容器直连 star-invest-lan，路径最短最稳。
# 拉取走 daocloud 镜像源（本网络直连 Docker Hub 层下载会被断）。
FRPC_IMAGE="${FRPC_IMAGE:-docker.m.daocloud.io/snowdreamtech/frpc:0.64.0}"
docker run -d --name invest-frpc --network docker_default --restart unless-stopped \
  -v "$RENDERED:/etc/frp/frpc.toml:ro" \
  "$FRPC_IMAGE"

sleep 3
docker logs invest-frpc 2>&1 | tail -5
echo ""
echo "隧道状态：docker logs -f invest-frpc"
echo "公网验证：curl http://47.92.235.34:8080/api/invest/ping"
