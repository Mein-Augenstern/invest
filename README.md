# invest · 投研管理台（公网多用户 · monorepo）

[![CI](https://github.com/Mein-Augenstern/invest/actions/workflows/ci.yml/badge.svg)](https://github.com/Mein-Augenstern/invest/actions/workflows/ci.yml)

> **公网可直接访问的管理形态产品**（章程 v2.2）：三端（微信小程序 · H5 · PC Web）覆盖
> 基金/股票/债券/理财的记账、统计、估值与规则化纪律信号。
> **平台与基础服务（登录/会员/网关/提醒）复用 star 系列**，本仓只做产品模块。
> 底线：不接自动下单、LLM 不预测涨跌、不做投资咨询（章程见 docs/prd/charter.md）。

## 公网访问

| 端 | 地址 | 登录方式 |
|----|------|----------|
| **PC 投研管理台** | **https://invest-6eq.pages.dev/**（Cloudflare · HTTPS · 主入口） | star 会员账号密码（登录页可注册） |
| PC 备用入口 | http://47.92.235.34/（ECS 直连，隧道故障时用） | 同上 |
| H5（移动网页） | http://47.92.235.34/h5/ | 同上（浏览器）；微信内打开自动登录 |
| 微信小程序 | 体验版 | 微信静默登录（设置页服务器切 gateway 模式 `http://47.92.235.34`） |

> 双入口：Cloudflare pages.dev（HTTPS，API 经 trycloudflare 隧道，CORS 单点放行
> + 网关重复 CORS 头已由 nginx 收敛）与 ECS IP 直连（同源备用）并行；
> 会员/登录由 star 平台基础服务承担（网关+会员部署于运营者 Mac Docker，frp 接入）。
> 隧道地址变更后重建部署：见 invest-web/README（VITE_API_BASE 注入）。
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

## 请求链路（S11 会员化 · 统一入口）

```
PC / H5 / 小程序 ──▶ http://47.92.235.34/（ECS nginx · 全同源 · 登录限流）
                     ├─ /                    → PC 投研管理台（SPA 静态）
                     ├─ /h5/                 → 移动端 H5
                     ├─ /api/invest/**       → invest :8790（star JWT 鉴权，ECS）
                     └─ /api/auth|member|family|reminder/** → frp 出站隧道
                                                          → Mac star 网关（JWT 签发）
                                                          → 会员/家庭/提醒服务
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
