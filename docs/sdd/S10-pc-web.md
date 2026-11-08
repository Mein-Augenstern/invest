# S10 · PC Web 端（invest-web）（Spec）

> 优先级 P1 · 状态：**进行中** · 前置：公网鉴权边界整改（2026-11-08 已完成，commit `138b029`）
> 原则：桌面端是移动端的**宽屏延伸**而非另起炉灶——领域逻辑仍全在 Python 端，
> 前端只做展示与录入，指标口径与小程序逐字段一致。
> 章程变更：PRD §5 负面清单原含「PC 端」，2026-11-08 经用户批准解禁（见 product.md 修订记录）。
> S09 预留的「S10 前端消费 data_stale」并入本 Spec（AC-5）。

## Problem

投研、对账、复盘是「坐下来看」的场景：持仓多列对比、长流水表、大尺寸净值曲线，
在手机上展示不下也操作不便。现状三条路都走不通：

1. **H5 在 PC 上是 420px 手机列**——屏幕利用率不到三成，图表被压成缩略图
2. **后端自带的 Tabler 管理台**（`webapp/templates/`）只绑 127.0.0.1、浏览器内无法携带 token，从未对外
3. **Cloudflare Pages 免费托管前端，但 HTTPS 页面不能调用 `http://<裸IP>` 的 API**（浏览器混合内容拦截，
   Cloudflare 代理也不接受裸 IP 回源）——需要域名 + Cloudflare Tunnel 打通

## User Stories

- **US-1**：作为用户，我在电脑上打开 `invest.<domain>`，输入一次 token 后进入完整的总览仪表盘
- **US-2**：作为用户，我在大屏上对比持仓表格（排序/筛选），点进标的看大尺寸净值曲线，鼠标悬停出十字线读数
- **US-3**：作为用户，我在电脑上用键盘补录流水，比手机快
- **US-4**：作为用户，小程序上能做的事 PC 上都能做（13 屏全量对齐）；截图识别在服务端不支持时给出明确说明而非白屏
- **US-5**：作为用户，行情数据过期时总览页显示「数据延迟」徽标，知道该手动拉数了

## Acceptance Criteria

### AC-1 鉴权门禁

- **GIVEN** 浏览器 localStorage 无 token
- **WHEN** 访问任意业务路由
- **THEN** 重定向到 `/login`，登录后回跳原路由
- **AND** 登录页以 `GET /api/invest/overview` 校验 token：401 显示「token 无效」，200 才持久化
- **AND** 任意请求返回 401 时清除 token 并回登录页（携带回跳地址）
- **AND** 顶栏「退出」清除 token

### AC-2 同源 HTTPS 链路

- **GIVEN** SPA 部署于 Cloudflare Pages（`invest.<domain>`）
- **WHEN** 前端请求 `/api/*`
- **THEN** 经 Pages `_redirects` 同 zone 代理至 `api.<domain>`（Cloudflare Tunnel → ECS `127.0.0.1:8790`）
- **AND** 浏览器视角为同源请求：后端无需开启 CORS，保持「无 CORS 即防御」设计
- **AND** 全链 HTTPS，ECS 不新增任何入站端口

### AC-3 指标口径一致（vitest 覆盖）

- **GIVEN** 后端返回 `xirr=0.1234`、`unrealized_pct=-0.05`、`pct_5y=37.5`
- **WHEN** 前端渲染
- **THEN** 依次显示 `+12.34%`、`-5.00%`、`37.5%`（前两者为小数×100，`pct_*` 已是百分数）
- **AND** 盈利红色、亏损绿色（红涨绿跌，与小程序一致）
- **AND** 空值统一显示 `—`

### AC-4 13 屏全量对齐 + 三态

- **GIVEN** 小程序 13 页面清单（product.md §3）
- **WHEN** PC 端上线
- **THEN** 每页均有对应桌面路由：总览 / 标的详情 / 流水 / 统计 / 信号 / 回测 / 周报 / 估值 / 日记 / 年度复盘 / 标的管理 / 截图识别 / 设置
- **AND** 每页覆盖 加载中 / 空态 / 错误+重试 三态（S06 模式）
- **AND** 写操作（记流水/删流水/记净值/日记/标的 CRUD）成功后刷新对应数据，失败展示后端 `error` 文案

### AC-5 数据延迟徽标（承接 S09）

- **GIVEN** `GET /api/invest/overview` 返回 `data_stale: true`
- **WHEN** 总览页渲染
- **THEN** 页头显示「数据延迟」标签，并提供「立即拉数」入口（`POST /pull` + 轮询 `/pull/status`）

### AC-6 服务端能力缺失时优雅降级

- **GIVEN** 后端运行在 Linux（无 macOS Vision），`POST /ocr` 返回 422 语义错误
- **WHEN** 用户在截图识别页上传图片
- **THEN** 页面展示后端返回的错误文案与「服务端不支持 OCR」说明，不白屏、不抛未捕获异常

### AC-7 质量门

- **GIVEN** 任一提交
- **WHEN** CI 运行
- **THEN** 前端 job：`vue-tsc --noEmit` 0 错 + vitest 全绿 + `vite build` 成功
- **AND** 后端 pytest 保持全绿

### AC-8 前端安全

- **GIVEN** 生产构建产物
- **WHEN** 对 `dist/` 做 token 字面量扫描
- **THEN** 不含任何 token（token 仅由用户在登录页输入，仅存浏览器 localStorage）

## Out of Scope

- 多用户 / 数据隔离（开放路线 O1 准入条件，另立 Spec）
- 移动端适配（手机继续用小程序 / H5）
- star 网关登录与家庭提醒（ECS 未部署 star 网关；PC 设置页显示说明）
- 后端新增业务端点（PC 端只消费现有 `/api/invest/*`；后端仅做 AC 必需的缺陷修复）
- 服务端渲染管理台（`webapp/templates/`）的改造或下线

## 实现要点

### 部署拓扑

```
浏览器 ──HTTPS──▶ invest.<domain>（Cloudflare Pages：SPA 静态资源）
                     │ _redirects: /api/*  →  https://api.<domain>/api/:splat  200（同 zone 代理）
                     ▼
               api.<domain>（Cloudflare Tunnel，出站隧道，免入站端口/免备案）
                     ▼
               ECS cloudflared 容器 ──▶ 127.0.0.1:8790 invest-app（token 鉴权 + Host 白名单）
```

降级预案：若同 zone 代理验证不通过，SPA 直连 `api.<domain>`，后端以 env 配置
`CORSMiddleware` 精确放行 `https://invest.<domain>` 单一 origin。

### 前端工程（`invest-web/`）

- Vite 5 + Vue 3 + TypeScript + vue-router + pinia（仅 auth 态）+ Element Plus + ECharts；pnpm；Node 20
- 风格：企业内部平台风（灰底白面板、统一页头与右侧操作区、表头灰底 600 字重），
  色板沿用小程序（主色 `#1652a8`、红涨绿跌），无渐变/emoji/重阴影
- 从 `invest-miniapp/src` 搬运：`types/index.ts`、`utils/format.ts`、`utils/markdown-lite.ts` 原样复用；
  `api/client.ts`（`uni.request` → `fetch` + 超时）、`api/config.ts`（uni storage → localStorage）薄适配

### 后端配套修复（各带 pytest 回归）

- `webapp/reportjob.py`：硬编码 SQLite → 按部署选择 store（MySQL 部署下周报读错库）
- `routes_mp.py` GLM key 路径：`data_dir.parent/config` 在容器内解析为 `/config`，与挂载点 `/app/config` 不符

## 验收记录

（实现后填写）
