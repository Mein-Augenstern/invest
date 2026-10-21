# 07 · 全仓架构总览（v2.0 公网化形态 · 2026-10-21）

> 本文是 invest 单仓（invest-platform + invest-miniapp）的架构、模块与调用关系的
> 唯一权威入口。边界与红线见 [00-charter.md](../prd/charter.md) v2.0。

## 1. 总览图

```mermaid
flowchart TB
  subgraph client["客户端层"]
    MP["微信小程序 invest-miniapp<br/>uni-app · Vue3 · TS · 13 页面"]
    H5["H5 调试端<br/>vite :5174 → 代理 /api"]
  end

  subgraph access["接入层"]
    GW["star 网关 :8080（Docker）<br/>wx-login 微信登录 · star JWT(HS256)<br/>/api/invest/** 转发"]
    NGINX["公网入口（待办）<br/>备案域名 + HTTPS + 限流"]
  end

  subgraph service["服务层 invest-platform（FastAPI/Python）"]
    API["routes_mp<br/>/api/invest/* 全部端点"]
    AUTH["TokenAuthMiddleware<br/>双模式 token | star"]
    ENGINE["引擎层<br/>portfolio · ledger · reporting<br/>strategy · valuation · ocr · pulljob"]
  end

  subgraph data["数据层（default_store 工厂切换）"]
    MY[("MySQL 8.0<br/>star 同实例 · 独立 invest 库<br/>INVEST_DB_URL 注入（生产）")]
    LITE[("SQLite data/invest.db<br/>缺省（开发/测试）")]
    FILES[("文件态<br/>trades.csv · portfolio yaml<br/>reports/*.md · glm.local.env")]
  end

  subgraph star["star 平台（家庭基础设施）"]
    MEMBER["member 服务<br/>JWT 签发"]
    FAMILY["family / reminder 服务<br/>家庭成员 · 待办提醒"]
  end

  subgraph ext["外部依赖"]
    QUOTE["行情源四级兜底<br/>东财 → 腾讯 → 新浪qfq → 新浪不复权"]
    GLM["智谱 GLM（可选）<br/>OCR 文本结构化"]
    VISION["macOS Vision（免费本地）<br/>截图 OCR"]
  end

  MP -->|"同 Wi-Fi / 公网域名(待)"| GW
  H5 -->|"/api 同源代理"| API
  GW --> MEMBER
  GW -->|"/api/invest/**"| API
  MP -->|"family/reminder 直连"| FAMILY
  API --> AUTH --> ENGINE
  ENGINE --> MY
  ENGINE --> LITE
  ENGINE --> FILES
  ENGINE --> QUOTE
  ENGINE --> GLM
  ENGINE --> VISION
  NGINX -.->|"待办：公网入口"| GW
```

**一次请求的路径**（gateway 模式）：
小程序 `uni.request` → star 网关 :8080（校验 JWT）→ 转发 invest :8790
（`TokenAuthMiddleware` 校验同一 HS256 密钥，纵深防御）→ 引擎层 → MySQL/SQLite。

## 2. 模块清单

### 2.1 前端 invest-miniapp（页面 13 · tabBar 5）

| 页面 | 职能 | 主要端点 |
|------|------|----------|
| `pages/overview/overview` | 总览：总资产/XIRR/缴存进度/信号摘要 | `/overview` `/signals` |
| `pages/summary/summary` | 统计：资产曲线（3月/1年/全部）、月度/日历 | `/asset-curve` `/summary` |
| `pages/trades/trades` | 流水列表 + 「记一笔」表单（按金额/份额）+ OCR 入口 | `/trades` |
| `pages/signals/signals` | 纪律信号 + 立即评估 | `/signals` `/signals/evaluate` |
| `pages/settings/settings`（tab「我的」） | 个人中心：profile/工具导航/服务器配置/GLM Key/拉数/提醒/退出 | `/settings/glm-key` `/pull` + star 直连 |
| `pages/instrument/instrument` | 标的详情：净值曲线 canvas/十字线/PE 分位带/交易事件 | `/instrument` 系列 |
| `pages/valuation/valuation` | 指数估值表 + 市场温度计（10 中证指数） | `/valuation` |
| `pages/diary/diary` | 投资日记（情绪五标签，类名 ASCII 红线） | `/diary` |
| `pages/annual/annual` | 年度账单（账户现金=缴存−申购 单列） | `/annual-report` |
| `pages/backtest/backtest` | 策略回测上端 | `/backtest` |
| `pages/report/report` | 周报生成（非 AI）+ 归档列表 | `/reports` |
| `pages/ocr/ocr` | 截图识别录入：选图 → `/ocr` → 草稿确认 | `/ocr` |
| `pages/instruments/instruments` | 标的管理 CRUD | `/instruments` |

关键前端机制：`api/auth.ts` 静默登录单飞；`api/client.ts` **401 自愈**
（清 token → 单飞重登 → 重试一次；`/api/auth/**` 与 direct 模式豁免）；
`api/config.ts` 双模式 storage（键前缀 `invest_`）。

### 2.2 后端 invest-platform（src/invest/）

| 模块 | 职责 |
|------|------|
| `webapp/routes_mp.py` | `/api/invest/*` 全部 HTTP 端点（单用户鉴权模型） |
| `webapp/security.py` | TokenAuthMiddleware：star JWT（HS256）/ LAN 静态令牌 |
| `webapp/deps.py` | `get_store`/`get_conf` 依赖注入（存储工厂入口） |
| `data/local.py` | SQLite 存储（WAL，全参数化 SQL） |
| `data/mysql_store.py` | MySQL 存储（star 同实例；23 项行为一致性对齐 SQLite；`default_store` 工厂在此） |
| `data/akshare_provider.py` 等 | 行情源 Provider（四级兜底） |
| `config.py` | 品类体系/series_kind 映射/数据目录（env 可覆盖） |
| `portfolio.py` | `load_portfolio`：yaml 种子 + DB 运行时标的合并 |
| `ledger/` | 账本：trades.csv 读写、contribute 口径（只进现金流不折份额） |
| `reporting.py` + `reporting_summary.py` | 月度盈亏/XIRR/资产曲线/日度/年报（账户现金单列） |
| `strategy.py` | 规则信号评估（估值分位定投/缴存/再平衡 → signals 表） |
| `valuation.py` | 10 指数估值表 + 市场温度计（5y 分位等权） |
| `ocr.py` | macOS Vision OCR + GLM 结构化（无 Key 降级纯文本） |
| `pulljob.py` | 拉数任务（后台线程）+ 完成后自动信号评估 |
| `cli.py` / `entry_server.py` | CLI（serve/pull/nav）与 uvicorn 入口 |

### 2.3 脚本资产

| 脚本 | 用途 |
|------|------|
| `invest-miniapp/scripts/postbuild-wxss.js` | wxss 多行规范化 + **反斜杠守卫**（WXSS 不支持 `\XXXX` 转义，构建即拦截） |
| `invest-miniapp/scripts/e2e-check.js` | automator E2E（`E2E_GATEWAY` 环境变量注入网关地址） |
| `invest-platform/scripts/dev-serve.sh` | 本机启动（`.env.dev` 注入密钥/DB URL，起 :8790/:8792） |
| `invest-platform/scripts/migrate_to_mysql.py` | SQLite → MySQL 幂等迁移 + 逐表行数校验 |
| `invest-platform/scripts/backup_mysql.sh` | mysqldump gzip 滚动 14 份（OSS 上传待 AK） |

## 3. 关键调用链

### 3.1 登录与鉴权（含 401 自愈）

```
小程序启动 → ensureLogin（token 存在则放行）
  ├─ 无 token：wx.login code → 网关 /api/auth/wx-login → star member 签发 JWT
  │            → storage(invest_token)（单飞：并发共享一次登录）
  └─ 有 token：直接带 Bearer 请求
       └─ 若 401（过期/密钥轮换）：client 清 token → 静默重登 → 原请求重试一次
          （登录端点自身豁免防死锁；direct 模式豁免）
```

JWT 参数红线：**密钥长度 [32,48) 字节**——star 侧 jjurt 按长度自动选算法，
≥48 字节切 HS384 而 invest 只认 HS256，直接全链路 401。

### 3.2 记一笔 / OCR 录入

```
表单提交 → POST /api/invest/trades → ledger 追加 trades.csv → 报表按需重算
OCR：选图 → POST /ocr(multipart) → Vision 提文本 → GLM 结构化(可选)
     → 返回流水草稿 → 用户确认 → 走记一笔
```

### 3.3 拉数与信号（后台）

```
「我的」→ 手动拉数 / cron → pulljob 线程
  → 四级行情源逐标拉取 → series 表幂等 upsert（REPLACE）
  → 完成后自动 evaluate_and_store_signals（注意返回 int 非 list）
```

### 3.4 star 家庭提醒（L4）

```
「我的」→ 投资提醒面板 → 直连网关 /api/reminder/rules（[投资] 前缀过滤）
  → 预设定投日/缴存补缴 → star 待办中心统一推送
```

## 4. 端口与环境变量

| 端口 | 进程 | 说明 |
|------|------|------|
| 8080 | star 网关（Docker） | 唯一小程序入口；公网化后经 Nginx/域名暴露 |
| 8790 | invest `--auth star` | 仅网关转发目标（127.0.0.1 绑定） |
| 8792 | invest `--lan` | 局域网直连模式（静态令牌） |
| 3306/3307 | star-mysql | 容器内 3306；本机映射 3307 |
| 9420/9421 | 微信开发者工具 automator | 调试 / E2E |

| 环境变量 | 用途 | 默认 |
|----------|------|------|
| `INVEST_JWT_SECRET` | star JWT 校验密钥（**无默认**，缺省全 401） | — |
| `INVEST_DB_URL` | `mysql://user:pass@host:3306/invest` 切 MySQL | 缺省 SQLite |
| `INVEST_DATA_DIR` / `INVEST_CONFIG_DIR` | 数据/配置目录覆盖 | `data/` |
| `INVEST_LAN_TOKEN` | `--lan` 模式静态令牌 | — |
| `E2E_GATEWAY` | e2e-check 网关地址注入（公开仓不落内网 IP） | — |

本机 dev 的密钥与连接串放 `invest-platform/.env.dev`（gitignore），
由 `scripts/dev-serve.sh` 注入；生产经 compose env 注入。

## 5. 部署形态

| | 当前（本机 dev） | 目标（公网化，待域名/执照） |
|---|---|---|
| 入口 | `http://<局域网IP>:8080`（开发者工具关域名校验 / 体验版调试模式） | 备案域名 + HTTPS + Nginx 限流 |
| 鉴权 | star JWT（新密钥已轮换） | 同左 + request 合法域名白名单 |
| 数据 | MySQL `invest_dev`（本机 star-mysql 容器） | 云端 star-mysql 同实例 `invest` 库 + 每日备份 |
| invest 进程 | dev-serve.sh 双端口 | 阿里云节点容器（Dockerfile 就绪） |

## 6. 已知约束（排查过的坑，改动前先读）

- **模拟器基础库锁 3.8.0**：`project.private.config.json` 才是 libVersion 真开关
  （优先级高于 project.config.json）；3.17.x 渲染层/元素查询有回归。
- **automator 锁 0.12.1**：0.13.0 连接回归。
- **WXSS 不支持 `\XXXX` 转义**：中文类名会被 Vue 编译器转义导致编译错误并静默
  炸掉 appLaunch（白屏 + 页面栈空 + automator page-meta null 三连锁）——
  类名一律 ASCII，postbuild 守卫兜底。
- 重建 dist 后开发者工具需彻底重启再挂项目（半写快照 + watch 冻结会报
  「项目根目录未找到 app.json」）；服务端口可用 `printf 'y\n' | cli islogin` 无人值守重开。
- `evaluate_and_store_signals` 返回 int；`contribute` 只进现金流不折份额；
  benchmarks pct 已是百分数而 xirr/drawdown 是小数（易错口径三连）。
