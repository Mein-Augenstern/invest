#!/usr/bin/env bash
# invest ECS 独立部署脚本（H5 + 后端 + MySQL）——2026-11-07 首次落地
#
# 与 docker-serve.sh（Mac 隧道形态）并存：本脚本把 invest 完整部署到 ECS 自身，
# 不依赖 Mac 开机（frpc 隧道断联不影响本部署）。
#
# 前置：
#   - ssh ecs 免密（~/.ssh/config Host ecs 条目）
#   - /opt/invest/ 下已有：mysql-init/invest-dump.sql、data/trades.csv、
#     config/portfolio.local.yaml、config/glm.local.env
#   - H5 产物已传 /opt/invest/h5/（构建命令见文件尾注释）
#   - 镜像已传并 load（invest-image.tar → star-site/platform-invest:latest）
set -euo pipefail

LAN_TOKEN="${INVEST_LAN_TOKEN:?缺 INVEST_LAN_TOKEN（与小程序体验版一致）}"

# ---- MySQL（700m：导入 5.9MB dump 时 400m 被 cgroup OOM 杀，实证）----
ssh ecs "docker rm -f invest-mysql 2>/dev/null || true; \
  docker run -d --name invest-mysql --restart unless-stopped -m 700m \
  -v /opt/invest/mysql-data:/var/lib/mysql \
  -e MYSQL_ROOT_PASSWORD=root123 mysql:8.0"
sleep 25
ssh ecs "docker exec invest-mysql mysql -uroot -proot123 \
  -e 'CREATE DATABASE IF NOT EXISTS invest_dev DEFAULT CHARSET utf8mb4' 2>/dev/null || true; \
  docker exec -i invest-mysql mysql -uroot -proot123 invest_dev < /opt/invest/mysql-init/invest-dump.sql 2>/dev/null || true"
# 注：dump 为单库导出（无 CREATE DATABASE），必须先建库再导入——
# 2026-11-07 实证：entrypoint init 静默失败于 No database selected（line 22）

# ---- invest 后端（8790 仅绑 127.0.0.1，公网经 nginx 反代）----
ssh ecs "docker network create invest_net 2>/dev/null || true; \
  docker network connect invest_net invest-mysql 2>/dev/null || true; \
  docker rm -f invest-app 2>/dev/null || true; \
  docker run -d --name invest-app --restart unless-stopped -m 350m --network invest_net \
  -p 127.0.0.1:8790:8790 \
  -e INVEST_AUTH_MODE=token \
  -e INVEST_MP_TOKEN='$LAN_TOKEN' \
  -e INVEST_DB_URL='mysql://root:root123@invest-mysql:3306/invest_dev' \
  -e INVEST_DATA_DIR=/data \
  -e INVEST_HOSTS_EXTRA=127.0.0.1,47.92.235.34 \
  -e TZ=Asia/Shanghai \
  -v /opt/invest/data:/data \
  -v /opt/invest/config:/app/config:ro \
  star-site/platform-invest:latest \
  uv run --no-dev uvicorn invest.webapp.main:app --host 0.0.0.0 --port 8790"
sleep 10

# ---- nginx server block（H5 静态 + /api 反代注入鉴权头）----
ssh ecs "cat > /etc/nginx/conf.d/invest-h5.conf << 'NGINX'
server {
    listen 80;
    server_name 47.92.235.34;
    root /opt/invest/h5;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ {
        proxy_pass http://127.0.0.1:8790;
        proxy_set_header Host \$host;
        proxy_set_header Authorization 'Bearer $LAN_TOKEN';
        proxy_read_timeout 120s;
    }
    location = /index.html { add_header Cache-Control no-cache; }
}
NGINX
nginx -t && nginx -s reload"

# ---- 验证 ----
echo "=== 验证 ==="
curl -s -m 10 -o /dev/null -w "H5: %{http_code}\n" "http://47.92.235.34/"
curl -s -m 15 "http://47.92.235.34/api/invest/overview" | head -c 120; echo
echo "手机浏览器访问：http://47.92.235.34/"

# ---- H5 构建命令（本地，注释状态）----
# cd invest-miniapp && 写 .env.production.local（三行 VITE_*，token 嵌入产物）：
#   VITE_INVEST_PUBLIC_SERVER=
#   VITE_INVEST_PUBLIC_MODE=direct
#   VITE_INVEST_PUBLIC_TOKEN=<LAN_TOKEN>
# 然后：npx uni build -p h5（条件编译 #ifdef H5 在 ts 文件内有效），
#       scp -r dist/build/h5/{index.html,assets} ecs:/opt/invest/h5/
#       构建后删除 .env.production.local（token 不入 git）
