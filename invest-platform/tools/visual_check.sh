#!/usr/bin/env bash
# 视觉验证关卡：对平台每个页面做无头Chrome截图，供人工/后续流程检查布局。
# 用法: bash tools/visual_check.sh [port]   （平台需已运行，默认 127.0.0.1:8790）
# 规则(CLAUDE.md): 任何 templates/static 改动，提交前必须跑本脚本并查看全部截图。
set -euo pipefail
PORT="${1:-8790}"
OUT="${HOME}/develop/ai-journey/invest-platform/data/reports/screens"
mkdir -p "$OUT"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo "未找到 Chrome，无法视觉验证"; exit 1; }

PAGES=("/:index" "/positions:positions" "/trades:trades" "/strategy:strategy" "/signals:signals" "/reports:reports" "/settings:settings" "/glossary:glossary" "/backtest:backtest")
for entry in "${PAGES[@]}"; do
  path="${entry%%:*}"; name="${entry##*:}"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --virtual-time-budget=8000 \
    --window-size=1440,2400 --screenshot="$OUT/$name.png" "http://127.0.0.1:$PORT$path" 2>/dev/null
  [ -s "$OUT/$name.png" ] && echo "[OK] $name -> $OUT/$name.png" || { echo "[FAIL] $name"; exit 1; }
done
echo "全部截图完成，请逐张检查（重点：卡片边界、图表是否溢出、文字换行）"
