#!/usr/bin/env bash
# invest ECS 独立部署脚本（H5 + 后端 + MySQL）——2026-11-07 首次落地
# 2026-11-08 安全整改：
#   - 密钥只存本目录 secrets/*.env（gitignored，600），经 scp 上传后以 --env-file 注入容器，
#     不出现在命令行/进程列表/仓库中
#   - nginx 不再注入 token：公网 API 必须由客户端携带 Bearer token
#   - dump 改由 docker-entrypoint-initdb.d 仅在数据目录首次初始化时导入——
#     旧写法每次重跑都会把过时 dump 重新导入覆盖线上数据
#
# 前置：
#   - ssh ecs 免密（~/.ssh/config Host ecs 条目）
#   - scripts/secrets/mysql.env（MYSQL_ROOT_PASSWORD + MYSQL_DATABASE）
#   - scripts/secrets/app.env（INVEST_MP_TOKEN + INVEST_DB_URL）
#   - /opt/invest/ 下已有：mysql-init/invest-dump.sql、data/trades.csv、
#     config/portfolio.local.yaml、config/glm.local.env
#   - H5 产物已传 /opt/invest/h5/（构建命令见文件尾注释）
#   - 镜像已传并 load（invest-image.tar → star-site/platform-invest:latest）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_DIR="$SCRIPT_DIR/secrets"
for f in mysql.env app.env; do
  [ -f "$SECRETS_DIR/$f" ] || { echo "缺 $SECRETS_DIR/$f（gitignored 密钥文件）" >&2; exit 1; }
done

# ---- 密钥上传（目录 700 / 文件 600，仅 root 可读）----
ssh ecs "mkdir -p /opt/invest/secrets && chmod 700 /opt/invest/secrets"
scp -q "$SECRETS_DIR/mysql.env" "$SECRETS_DIR/app.env" ecs:/opt/invest/secrets/
ssh ecs "chmod 600 /opt/invest/secrets/*.env"

# ---- MySQL（700m：导入 5.9MB dump 时 400m 被 cgroup OOM 杀，实证）----
# 数据目录已存在时 initdb 自动跳过，重跑本脚本不会触碰线上数据
ssh ecs "docker rm -f invest-mysql 2>/dev/null || true; \
  docker run -d --name invest-mysql --restart unless-stopped -m 700m \
  --env-file /opt/invest/secrets/mysql.env \
  -v /opt/invest/mysql-data:/var/lib/mysql \
  -v /opt/invest/mysql-init:/docker-entrypoint-initdb.d:ro \
  mysql:8.0"
sleep 25

# ---- invest 后端（8790 仅绑 127.0.0.1，公网经 nginx 反代，客户端自带 token）----
ssh ecs "docker network create invest_net 2>/dev/null || true; \
  docker network connect invest_net invest-mysql 2>/dev/null || true; \
  docker rm -f invest-app 2>/dev/null || true; \
  docker run -d --name invest-app --restart unless-stopped -m 350m --network invest_net \
  -p 127.0.0.1:8790:8790 \
  --env-file /opt/invest/secrets/app.env \
  -e INVEST_AUTH_MODE=token \
  -e INVEST_DATA_DIR=/data \
  -e INVEST_GLM_KEY_FILE=/data/glm.local.env \
  -e INVEST_HOSTS_EXTRA='127.0.0.1,47.92.235.34,*.trycloudflare.com' \
  -e TZ=Asia/Shanghai \
  -v /opt/invest/data:/data \
  -v /opt/invest/config:/app/config:ro \
  star-site/platform-invest:latest \
  uv run --no-dev uvicorn invest.webapp.main:app --host 0.0.0.0 --port 8790"
sleep 10

# ---- nginx server block（H5 静态 + /api 反代，不注入鉴权头）----
scp -q "$SCRIPT_DIR/ecs-invest-h5.conf" ecs:/etc/nginx/conf.d/invest-h5.conf
ssh ecs "nginx -t && nginx -s reload"

# ---- 验证：无 token 必须 401（鉴权边界生效）----
echo "=== 验证 ==="
curl -s -m 10 -o /dev/null -w "H5: %{http_code}\n" "http://47.92.235.34/"
curl -s -m 10 -o /dev/null -w "API 无 token（预期 401）: %{http_code}\n" "http://47.92.235.34/api/invest/overview"
echo "手机浏览器访问：http://47.92.235.34/（首访在「我的」页输入 token）"

# ---- H5 构建命令（本地，注释状态；token 不嵌入产物）----
# cd invest-miniapp && 写 .env.production.local（三行 VITE_*，token 留空）：
#   VITE_INVEST_PUBLIC_SERVER=
#   VITE_INVEST_PUBLIC_MODE=direct
#   VITE_INVEST_PUBLIC_TOKEN=
# 然后：npx uni build -p h5（条件编译 #ifdef H5 在 ts 文件内有效），
#       scp -r dist/build/h5/{index.html,assets} ecs:/opt/invest/h5/
#       构建后删除 .env.production.local
