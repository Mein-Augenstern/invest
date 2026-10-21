# invest · 个人投资记账与纪律工具（单仓 monorepo）

> 作者自用起步、**分阶段开放中**（白名单 → 公开发布，路线见 [docs/prd/product.md](docs/prd/product.md) §6）。
> 前后端同仓：一个迭代周期内 API 契约与前端同步改动，单人项目 monorepo 最省同步成本。
> 登录/网关/鉴权接入 star 平台，业务与 star 系列完全独立。
> 底线：不接自动下单、LLM 不预测涨跌、不做投资咨询（章程见 docs/prd/charter.md）。

## 布局

| 目录 | 说明 |
|------|------|
| [docs/](docs/) | 全仓文档（编号制）：00 章程 · 02 规则书 · 06 API 契约 · 07 架构总览 · 08 前端工程指南 等 |
| [invest-platform/](invest-platform/) | 后端（Python/FastAPI）：账本 XIRR、估值风险指标、策略信号、回测、OCR；**数据层双后端**（MySQL=star 同实例 / SQLite=开发测试）；star 微服务形态（`/api/invest/**`，star JWT 纵深防御） |
| [invest-miniapp/](invest-miniapp/) | 前端（uni-app+Vue3+TS 微信小程序）：总览/统计/流水/信号/我的（个人中心），微信登录走 star 网关，401 自愈 |

## 快速开始

```bash
# 后端（CLI 与 Web 平台，缺省 SQLite；INVEST_DB_URL=mysql://… 切 MySQL）
cd invest-platform && uv sync && uv run python -m invest serve   # http://127.0.0.1:8790

# 后端（star 微服务形态：挂 star 网关，微信登录）
#   本机 dev 一键起（.env.dev 注入密钥/DB URL，见 scripts/dev-serve.sh 头部模板）
./scripts/dev-serve.sh

# 前端（微信开发者工具导入 dist/release/mp-weixin）
cd ../invest-miniapp && pnpm install --dangerously-allow-all-builds && pnpm build:mp-weixin
```

## 请求链路

```
微信小程序 ──▶ star 网关 :8080（wx-login 微信登录 → star JWT HS256）
                 └─ /api/invest/** ──▶ invest-platform :8790（TokenAuth 纵深防御）
                                            └─▶ MySQL（star 同实例 invest 库）/ SQLite
小程序（家庭提醒）──▶ star reminder 服务（待办中心统一推送）
pulljob / CLI / cron ──▶ invest-platform 同一引擎 ──▶ 行情源四级兜底
```

> **公开仓安全约定**：代码不内置任何密钥。star 鉴权模式必须注入
> `INVEST_JWT_SECRET`（与 star 平台各服务 `jwt.secret` 一致，长度 [32,48) 字节）；
> MySQL 连接串经 `INVEST_DB_URL` 注入。
> 真实持仓/流水/配置/密钥经 gitignore 留在本机（`/data/`、`portfolio.local.yaml`、`.env.dev`），不入库。

**架构与调用总览：[docs/tech/architecture.md](docs/tech/architecture.md)**
API 契约：[docs/tech/backend/api-contract.md](docs/tech/backend/api-contract.md)
数据源与口径登记：[docs/business/data-sources.md](docs/business/data-sources.md)

## 历史

本仓由 ai-journey 的 invest-platform/ 与 invest-miniapp/ 经 subtree 合并成仓（历史提交保留，`git log` 全量可溯）。
