# S11 · star 基础服务上云与会员化（Spec）

> 优先级 P0 · 状态：**Spec 待实现** · 前置：S10 已上线（invest-6eq.pages.dev，2026-11-08 生产验收）
> 章程依据：v2.2（2026-11-08 用户拍板）——公网管理形态产品定位；基础服务必须 star 系列。
> 原则：**平台能力不重造**——登录/会员/JWT/提醒全部复用 star；invest 只做产品模块，
> 数据隔离以 member_id 贯穿产品数据全链路。

## Problem

产品定位已是**直接公网可访问的管理形态产品**，但现状是单用户静态 token 形态：

1. 无会员体系——访客只有一个手输 token 的登录框，无注册/账号/会话管理
2. 基础服务缺位——star 网关/会员/提醒只部署在 Mac（frp 隧道），公网 ECS 上没有；
   Mac 关机即小程序微信登录与家庭提醒全部失效
3. 数据全局共享——trades 为无 owner 维度的 CSV 单账本，放任何第二个用户进来
   即互相可见（章程 v1.1 已预留"如需隔离再立项"，本 Spec 即该立项）
4. 无角色/限流/审计——管理形态产品的运营基本面缺失

## User Stories

- **US-1**：作为访客，我在 PC 登录页用账号密码注册/登录，获得自己的空账本，开始记账
- **US-2**：作为会员，我的账本/标的/日记/信号只有我和运营者可见，其他会员不可见
- **US-3**：作为运营者（admin），我能管理会员（邀请/禁用/重置），并保留全量数据运维入口
- **US-4**：作为会员，我在微信小程序静默登录（wx-login）后看到与 PC 端同一本账
- **US-5**：作为会员，我设置的投资提醒在服务端按时推送，不依赖运营者电脑开机
- **US-6**：作为运营者，登录接口有限流保护，关键写操作有审计记录可查

## Acceptance Criteria

### AC-1 star 基础服务最小集上云（ECS）

- **GIVEN** ECS（2C2G）已运行 invest-mysql/invest-app/invest-tunnel
- **WHEN** 部署 star 网关 + star member 最小集（提醒服务可延后）
- **THEN** `GET /api/auth/login` 链路与会员 CRUD 在 ECS 可达（健康检查通过）
- **AND** 全部容器内存占用实测后总和 ≤ 机器上限（超限按 architecture.md §5.1 取舍序处理）
- **AND** star 服务与 invest 共用同一 MySQL 实例（各自独立库）

### AC-2 invest 切换 star 鉴权

- **GIVEN** star 网关已在 ECS 以共享 JWT 密钥（`INVEST_JWT_SECRET`，与 star `jwt.secret` 一致）运行
- **WHEN** invest-app 以 `INVEST_AUTH_MODE=star` 重建
- **THEN** 经网关转发的请求（携带 star JWT）通过 TokenAuth 校验并取得 member_id
- **AND** 无 JWT / 伪造 JWT 请求返回 401（pytest 覆盖，沿用 test_star_auth 模式）
- **AND** 静态 token 模式退役（`INVEST_MP_TOKEN` 不再注入生产）

### AC-3 三端登录 UX

- **GIVEN** PC 登录页与小程序
- **WHEN** 会员在 PC 输入账号密码（`POST /api/auth/login` 经网关）
- **THEN** 获得 star JWT 并持久化本地，进入管理台；401 时回登录页
- **AND** 小程序恢复 wx-login 静默登录直连 ECS 网关（不再手输 token）
- **AND** 旧 token 登录入口下线（README 公网说明同步更新）

### AC-4 会员数据隔离（本 Spec 核心）

- **GIVEN** 会员 A 与会员 B 均已登录
- **WHEN** A 请求 `/api/invest/overview`、`/trades`、`/diary`、`/instruments` 等
- **THEN** 仅返回 A 的数据；B 的任何数据不可见、不可改（pytest 越权用例）
- **AND** trades 账本自 CSV 迁移 MySQL，新增 `member_id` 列；CSV 保留为导出格式
- **AND** instruments（DB 部分）/signals/diary/reports 等用户数据同列 member_id
- **AND** 行情序列、指数目录等公共数据不隔离（全会员共享缓存）

### AC-5 角色

- **GIVEN** star member 携带角色信息（admin/member）
- **WHEN** admin 请求会员管理入口（列表/邀请/禁用）
- **THEN** 操作生效并留审计；member 请求同等入口返回 403
- **AND** admin 可进入"运营视图"（全会员数据健康/备份），但读取会员账本明细
  仍需审计留痕

### AC-6 限流与审计

- **GIVEN** 公网直连流量
- **WHEN** 登录接口被高频尝试（>10 次/分钟/来源）
- **THEN** 网关/nginx 层限流生效（429），锁定窗口
- **AND** 登录成功/失败、会员管理操作、账本写操作落审计日志（who/what/when/traceId）

### AC-7 提醒上云（可在 AC-1 后单独交付）

- **GIVEN** star reminder 服务部署于 ECS
- **WHEN** 会员设置投资提醒（缴存日/定投日）
- **THEN** 到点经服务端推送（微信服务通知），不依赖 Mac 开机

### AC-8 迁移与回滚

- **GIVEN** 现有运营者的 CSV 账本与 MySQL 数据
- **WHEN** 执行迁移脚本
- **THEN** 全量数据归属运营者 member_id，逐项对账（流水条数/总资产/XIRR 与迁移前一致）
- **AND** 迁移脚本幂等，可重跑；迁移前自动备份

## Out of Scope

- 计费/付费墙（负面清单与数据主权承诺不变：导出永久免费）
- 公开注册的开放节奏与邀请码策略（产品运营决策，另立迭代）
- ICP 备案与小程序正式版上架（主体资质流程，非工程项）
- 家庭共享账本（多 member 合并视图，未来迭代）
- PC 端会员管理界面的完整运营台（先以最小可用：列表+禁用+邀请）

## 实现要点

1. **第一步勘察（决定可行性）**：star-site-backend 的网关/member 最小启动集
   （依赖的中间件、配置、是否可独立于其余微服务运行）；ECS 实测 JVM 压堆后
   RSS，对照 architecture.md §5.1 内存预算；超限取舍序：MySQL 600m（重导验证）
   → reminder 延后 → 建议升配 2C4G（约 +¥20-30/月，需用户决策）。
2. **JWT 一致性**：`INVEST_JWT_SECRET` 与 star 各服务 `jwt.secret` 同值，
   长度 [32,48)（≥48 会切 HS384，两端必须一致）；invest 已支持 HS256/HS384。
3. **member_id 贯穿**：FastAPI 依赖注入 `get_member_id`（从 TokenAuth 解析结果
   取 `sub`）；store 层查询全部追加 `WHERE member_id=?`（参数化，Mimosa 合规）；
   trades 迁库后 ledger 读写走 MySQL（保留 CSV 导出器）。
4. **过渡兼容**：迁移期间 token 模式仅保留给运营者本人（env 双开窗口 ≤1 迭代），
   三端全部切 star 后关闭。
5. **安全约束（Mimosa）**：服务端任何对外请求仅 http/https 且拒绝
   localhost/环回/私有地址；SQL 全参数化；审计日志不含金额明文（只记操作与条数）。

## 验收记录

**2026-11-08 · P1 会员化落地（AC-1/2/3/6 首批通过，统一入口形态）**

部署事实（用户拍板：Mac 为 star 基础服务正式部署机，替代"全部上 ECS"的内存紧方案）：

- AC-1 ✅（形态修订）：star 网关+member 运行于 Mac Docker（32G，compose
  `restart: unless-stopped`），经 frp 出站隧道接入 ECS 统一入口；
  网关 `INVEST_UPSTREAM` 已指回 ECS（消除旧 Mac 数据面）。
  ⚠️ family 未起：容器构建依赖本机 m2 的 starsite 组件（Maven Central 发布待办），
  其接口（家庭成员列表）此前即 503，非本次回归
- AC-2 ✅：invest-app `INVEST_AUTH_MODE=star` + 共享 `INVEST_JWT_SECRET`；
  无 JWT→401 / 伪造 JWT→401 / 有效 star JWT→200（实测三态）；静态 token 退役
- AC-3 ✅（PC+H5）：PC 登录页账密登录/注册（经同源 /api/auth/**）；
  H5 新增账密登录页（浏览器无微信环境）+ 401 回登录页；JWT 仅存本机。
  小程序端待用户在设置页切换 gateway 模式（wx-login 静默，代码既有）
- AC-6 ✅（限流部分）：nginx `/api/auth/` 每 IP 10r/m（burst 10）→ 实测第 12 次起 429；
  审计日志未做（余项）
- 统一入口：`http://47.92.235.34/`（PC 根 + /h5/ + 双 API 路由，全同源）；
  trycloudflare 隧道与 pages.dev 退役（临时方案清理）
- 运营者账号：member #31（凭据在 `scripts/secrets/member.env`，gitignored）

**余项（P2 数据隔离 = 本 Spec 核心）**：AC-4 member_id 全链路隔离、AC-5 角色
（star member 无 role 字段，拟 invest 侧 ADMIN_MEMBER_IDS）、AC-7 提醒上云、
AC-8 迁移对账、审计日志、family 构建（依赖组件发布）。
