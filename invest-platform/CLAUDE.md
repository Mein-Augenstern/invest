# invest-platform 工作规则

本文件是 Claude Code 在本子项目内工作时的强制约束，先读这里再动手。

## 项目定位（不可违背）

- 这是**决策支持系统**：输出"建议信号"，永远不自动下单。
- LLM 的职责是信息压缩、逻辑推理、报告生成；禁止输出"预测明天涨跌"类内容。
- 仅个人使用，不对外提供服务。

## 安全红线

- `config/portfolio.local.yaml`、`data/` 已被 gitignore：真实持仓/流水是敏感数据，**绝不提交**。
- 每次提交前检查 `git status`，确认没有敏感文件混入。
- Web 平台仅绑定 127.0.0.1；对外暴露属章程红线变更，须用户明确批准。

## 架构约定

- Python 3.10+ + uv；依赖：akshare/pandas/pyyaml/requests + fastapi/uvicorn/jinja2（Web平台，
  用户确认的升级需求；刻意不用 fastapi[standard] 保持最小化）+ markdown（概念笔记页渲染
  data/glossary/*.md）+ dev组 httpx（TestClient 硬依赖）。
- **概念笔记**：`data/glossary/*.md` 一个文件一个概念（首行 `# 概念名`），页面自动收录；
  用户会持续补充，讲解过的新概念应主动沉淀成文件。
- **视图模型唯一实现在 `reporting.py`**：webapp 与 CLI 都只调它；禁止出现第二份"持仓+市值+盈亏+XIRR"计算。
- **webapp/ 分层铁律**：views.py 只调 reporting + Jinja2 filter，禁止直接 import pandas/metrics/ledger 做计算
  （表单落盘走 ledger.trades 写入函数）；页面路由一律同步 `def`（pandas 丢线程池）；
  页面刷新只读，写操作（评估信号/生成周报/拉数）只经显式 POST。
- 数据获取统一走 `DataProvider` 协议；akshare 调用集中在 `akshare_provider.py`；拉数管线在 `pipeline.run_pull`
  （CLI 与 Web 共用）。
- 原始数据落地 SQLite（`data/invest.db`），表 `series(instrument,kind,date,close,source)` 带数据血缘；幂等 upsert。
- 流水写入（append/delete/校验）走 `ledger.trades` 的锁内路径（`save_validated_trade`），不要绕开。
- 估值口径的选用与变更必须登记 `docs/03-data-sources.md`；Web 架构与安全模型见 `docs/04-web-architecture.md`。
- 图表用 `webapp/static/js/invest-charts.js`（契约化、tooltip 自包含）；dataviz 配色 token 在
  `.viz-scope` 命名空间，不映射 Tabler 变量，vendor 的 tabler.min.css 严禁修改。

## 常用命令

```bash
uv run pytest                          # 单测
uv run python -m invest serve          # Web管理平台 127.0.0.1:8790（主入口）
uv run python -m invest selfcheck      # 数据源连通性
uv run python -m invest pull-data      # 拉数入SQLite
uv run python -m invest snapshot       # 持仓快照(markdown)
uv run python -m invest signals        # 策略信号(--confirm/--ignore ID)
uv run python -m invest report --ai    # 周报+GLM解读(需INVEST_GLM_API_KEY)
```
已退役：`invest dashboard`（Web总览页替代）、`invest entry`（/trades 页替代，deprecated）。

## 工作流

- 完成关键里程碑 → 更新 `docs/01-roadmap.md` 状态 → commit 并 push（用户已授权自动 push）。
- commit message 用 conventional commits 风格，可中文描述，如 `feat(ledger): XIRR计算与单测`。
- 策略参数变更必须更新 `docs/02-strategy-rules.md` 并写明理由，防止"挪门柱"。
- 收益率一律用资金加权（XIRR）口径；重构涉及报告输出时先抓 golden 基线，改完逐字节 diff。
- **UI 视觉验证关卡**：凡改动 `webapp/templates/` 或 `webapp/static/`，提交前必须
  `bash tools/visual_check.sh` 生成全部页面截图并**逐张查看**（重点：卡片边界、图表溢出、文字换行）。
  服务端测试（HTTP 200/内容断言）看不见 CSS 布局缺陷——重叠类 bug 只能靠截图发现，此规则源于实际教训。
- **截图必须用"矮窗口"**：高窗口（≥内容高度）截图会掩盖"页面不可滚动"类缺陷；
  布局验证需 viewport 短于内容（如 1692×1058），并量测 `documentElement.scrollHeight > innerHeight`。
- **自建 CSS 类名必须先查 Tabler 是否已有同名类**（grep vendor/tabler.min.css）：
  `card-chart` 撞名 Tabler 内置类（height:3.5rem）导致图表卡全部塌成 56px、页面不可滚动——
  本次最深刻的教训。图表卡用 `chartcard`，网格用自控 `.chart-grid/.stat-grid`（不依赖框架 row/col 拉伸）。
- 图表必须放在 `.viz-scope .chart-box` 刚性隔离盒内（固定高度 + `contain` + `overflow:hidden`），
  不允许脱离该容器自绘尺寸。
