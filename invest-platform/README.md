# invest-platform · 个人投研与决策支持平台

> 定位：**决策支持系统**——记清楚（账本）、看明白（估值与风险）、有纪律（策略信号与复盘）。
> 红线：不接券商自动下单、不对外提供服务、真实持仓数据不出本机。详见 [docs/00-charter.md](docs/00-charter.md)。

## 当前覆盖

- **品类体系（P9）**：基金（场外/ETF）、股票、债券、理财/固收——统一账本（XIRR）、统一风险视角、分品类行情路由
- 个人养老金账户：某中证红利 ETF 联接基金（Y 份额，真实代码/流水经 gitignore 留在本机）——真实账本已对账
- A股证券账户：消费50 类 ETF——基准指数估值与策略信号已就绪
- **微信小程序端（P10/P11）**：[invest-miniapp](../invest-miniapp/)（同仓）——总览/流水/信号/周报 + 标的详情（净值曲线），`serve --lan` 局域网令牌直连

## 快速开始（推荐：Web 管理平台）

```bash
uv sync                              # 安装依赖
uv run python -m invest serve        # 打开 http://127.0.0.1:8790（仅本机）
```

页面：**总览**（主数字+持仓+估值+信号）· **持仓**（账本+PE历史图+指数对比）· **流水**（录入/删除/缴存进度）
· **信号**（评估/确认/忽略）· **报告**（周报生成+历史，GLM解读可选）· **设置**（手动拉数+策略参数）。

首次使用：复制 `config/portfolio.example.yaml` → `portfolio.local.yaml` 填代码；设置页点"手动拉数"。

## CLI（与 Web 共用同一实现）

```bash
uv run python -m invest selfcheck    # 数据源连通性检查
uv run python -m invest pull-data    # 拉取行情/净值/指数估值入本地SQLite
uv run python -m invest snapshot     # 持仓+收益快照(Markdown)
uv run python -m invest signals      # 策略信号评估与留痕（--confirm/--ignore ID）
uv run python -m invest report       # 周报=快照+信号；--ai 附加GLM解读
uv run python -m invest nav <id> --value 1.0234   # 理财等无行情品种：手工净值（--list 查看）
uv run python -m invest serve --lan  # 局域网模式：小程序/手机访问（自动生成令牌）
uv run pytest                        # 单测
```

已退役：`invest dashboard`（Web 总览页替代）、`invest entry`（/trades 页替代，命令暂留 deprecated 提示）。

## GLM 解读（可选）

```bash
export INVEST_GLM_API_KEY=<智谱API Key>      # 必需
export INVEST_GLM_MODEL=glm-5.3             # 可选，默认 glm-5.3
uv run python -m invest report --ai          # 或 报告页勾选"附加GLM解读"
```
AI 解读边界（章程红线）：只做信息压缩与推理、必须引用报告数字、不预测涨跌；无 Key 优雅降级。

## 定时运行（macOS cron）

```bash
crontab -e
# 交易日 18:17 拉数+信号（PATH 需含 uv）：
17 18 * * 1-5 cd ~/develop/invest/invest-platform && ~/.local/bin/uv run python -m invest pull-data >> data/cron.log 2>&1 && ~/.local/bin/uv run python -m invest signals >> data/cron.log 2>&1
```

## 持仓配置与数据安全

- 真实配置 `config/portfolio.local.yaml`、数据 `data/`（trades.csv / invest.db / reports）均被 **gitignore**——敏感数据不出本机。
- Web 平台仅绑定 127.0.0.1 并校验 Host 头；详见 [docs/04-web-architecture.md](docs/04-web-architecture.md) 安全模型一节。

## 文档

| 文档 | 内容 |
|------|------|
| [docs/00-charter.md](docs/00-charter.md) | 项目章程：定位、边界、红线 |
| [docs/01-roadmap.md](docs/01-roadmap.md) | 路线图与里程碑跟踪（活文档） |
| [docs/02-strategy-rules.md](docs/02-strategy-rules.md) | 策略规则书（版本化，防"挪门柱"） |
| [docs/03-data-sources.md](docs/03-data-sources.md) | 数据源与口径登记表 |
| [docs/04-web-architecture.md](docs/04-web-architecture.md) | Web 平台架构、路由/API、安全模型、vendoring |
| [docs/06-miniapp.md](docs/06-miniapp.md) | 小程序端架构：拓扑、令牌安全模型、/api/mp 契约、E2E |

## 路线图

P0-P5、P7（Web 平台）、P8（回测）已完成 → **P9 扩品类记账 + P10 微信小程序端已完成（2026-10-18）**；
后续：债券 YTM/久期、个股财报检查清单、GLM 基金季报解读、对账单 PDF 解析。详见 [docs/01-roadmap.md](docs/01-roadmap.md)。
