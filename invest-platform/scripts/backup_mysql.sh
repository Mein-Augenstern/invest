#!/usr/bin/env bash
# invest MySQL 库备份：mysqldump → data/backups/（gzip，保留最近 14 份）。
# 上云后建议 cron 每日跑一次，并把产物同步到 OSS（待 AK 就绪后补 ossutil 段）。
# 连接串复用 .env.dev 的 INVEST_DB_URL（mysql://user:pass@host:3306/invest）。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.dev ]; then
  set -a; source .env.dev; set +a
fi
: "${INVEST_DB_URL:?缺 INVEST_DB_URL（写入 invest-platform/.env.dev）}"

URL="${INVEST_DB_URL#mysql://}"
USER="${URL%%:*}"
REST="${URL#*:}"
PASS="${REST%%@*}"
HOSTPORT_DB="${REST#*@}"
HOST="${HOSTPORT_DB%%:*}"
REST2="${HOSTPORT_DB#*:}"
PORT="${REST2%%/*}"
DB="${HOSTPORT_DB##*/}"

OUT="data/backups/${DB}-$(date +%Y%m%d-%H%M%S).sql.gz"
mkdir -p data/backups
# mysqldump 不在 PATH 时兜底常见安装位；都在 DB 所在机跑时也可换 docker exec 形态
DUMP="$(command -v mysqldump || echo /usr/local/mysql/bin/mysqldump)"
[ -x "$DUMP" ] || DUMP="$(command -v mysqldump || true)"
[ -n "$DUMP" ] && [ -x "$DUMP" ] || { echo "mysqldump 不可用（安装 mysql-client 或改用 docker exec star-mysql mysqldump）"; exit 3; }
"$DUMP" -h"$HOST" -P"$PORT" -u"$USER" -p"$PASS" --single-transaction --routines "$DB" | gzip > "$OUT"
ls -t data/backups/${DB}-*.sql.gz | tail -n +15 | xargs -r rm --
echo "备份完成: $OUT ($(du -h "$OUT" | cut -f1))"
