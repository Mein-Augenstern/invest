# invest · 投研管理台（公网多用户 · monorepo）

[![CI](https://github.com/Mein-Augenstern/invest/actions/workflows/ci.yml/badge.svg)](https://github.com/Mein-Augenstern/invest/actions/workflows/ci.yml)

> **公网可直接访问的管理形态产品**（章程 v2.2）：三端（微信小程序 · H5 · PC Web）覆盖
> 基金/股票/债券/理财的记账、统计、估值与规则化纪律信号。
> **平台与基础服务（登录/会员/网关/提醒）复用 star 系列**，本仓只做产品模块。
> 底线：不接自动下单、LLM 不预测涨跌、不做投资咨询（章程见 docs/prd/charter.md）。

## 公网访问

| 端 | 地址 | 说明 |
|----|------|------|
| **PC Web（投研管理台）** | **https://invest-6eq.pages.dev** | Cloudflare Pages 免费托管 · HTTPS；token 门禁（会员化 S11 进行中，将切换 star 账号登录） |
| H5（移动网页） | http://47.92.235.34/ | ECS nginx 同源部署；首访在「我的」页输入 token |
| 微信小程序 | 体验版 | uni-app 构建；微信登录走 star 网关 |

> PC/H5 访问 token 见部署密钥说明（运营者持有，不入库）；
> 产品定位与会员化路线见 [docs/prd/product.md](docs/prd/product.md) §6。

## 布局

| 目录 | 说明 |
|------|------|
| [docs/](docs/) | 全仓文档：章程 · PRD · SDD Specs · API 契约 · 架构总览 等 |
| [invest-platform/](invest-platform/) | 后端（Python/FastAPI）：账本 XIRR、估值风险、策略信号、回测、OCR；数据层双后端（MySQL 生产 / SQLite 开发测试）；star JWT 纵深防御 |
| [invest-web/](invest-web/) | **PC Web 端（S10）**：Vue3 + TS + Element Plus + ECharts，登录 + 13 屏全量；Cloudflare Pages 部署 |
| [invest-miniapp/](invest-miniapp/) | 前端（uni-app+Vue3+TS 微信小程序）：13 页面，微信登录走 star 网关，401 自愈 |

## 快速开始

```bash
# 后端（CLI 与 Web 平台，缺省 SQLite；INVEST_DB_URL=mysql://… 切 MySQL）
cd invest-platform && uv sync && uv run python -m invest serve   # http://127.0.0.1:8790

# PC Web（vite 代理 /api → ECS；本机联调 INVEST_DEV_API=http://127.0.0.1:8790）
cd ../invest-web && pnpm install && pnpm dev                     # http://localhost:5175

# 微信小程序（开发者工具导入 dist/release/mp-weixin）
cd ../invest-miniapp && pnpm install --dangerously-allow-all-builds && pnpm build:mp-weixin
```

## 请求链路（当前 · S11 会员化后以 star 网关为统一入口）

```
PC Web（pages.dev）──HTTPS──▶ cloudflared 隧道 ──▶ invest :8790（token 鉴权，CORS 单点放行）
H5（ECS 同源）──▶ nginx /api 反代 ──▶ invest :8790
微信小程序 ──▶ star 网关（wx-login → star JWT）──▶ /api/invest/** ──▶ invest :8790（纵深校验）
家庭提醒 ──▶ star reminder 服务
pulljob / 定时任务（starsite 同语义分布式锁）──▶ 行情源四级兜底
```

> **公开仓安全约定**：代码不内置任何密钥。生产密钥经 `scripts/secrets/*.env`
> （gitignored）以容器 `--env-file` 注入；star 鉴权注入 `INVEST_JWT_SECRET`
> （与 star 平台一致，长度 [32,48) 字节）；真实数据 gitignore 留在服务端。

**架构与调用总览**：[docs/tech/architecture.md](docs/tech/architecture.md)
（含 S11 目标拓扑：star 基础服务底座）
API 契约：[docs/tech/backend/api-contract.md](docs/tech/backend/api-contract.md)

## 历史

本仓由 ai-journey 的 invest-platform/ 与 invest-miniapp/ 经 subtree 合并成仓，
2026-11 新增 invest-web/（S10 PC 端）。`git log` 全量可溯。
