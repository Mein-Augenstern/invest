# 06 · 小程序 API 契约（invest-miniapp ↔ invest-platform）

> P10 产物，P13 起接入 star 平台基础设施。小程序是 invest-platform 的**移动入口**，不是独立系统：
> 领域逻辑（账本/指标/策略）全部在 Python 端，小程序只做展示与录入。
> 前端工程指南见 [08-miniapp-engineering.md](../frontend/miniapp-engineering.md)，全仓架构见 [07-architecture.md](../architecture.md)。

## 一、拓扑（v2.0 公网化形态）

```
┌────────────────────┐  wx.login   ┌──────────────────────────────────────────────┐
│  invest-miniapp    │────────────▶│  star 网关 :8080（容器）                      │
│  (同仓 uni-app)     │  /api/auth/ │  · JwtGlobalFilter 统一校验 star JWT          │
│                    │  wx-login   │  · invest-route: /api/invest/**              │
│  13 页面·5 tab     │────────────▶└───────────────┬──────────────────────────────┘
│  总览/统计/流水/    │  /api/invest/** (Bearer star JWT)          │ host.docker.internal
│  信号/我的          │◀────────────────────────────────────────── ▼
└────────────────────┘            ┌──────────────────────────────────────────────┐
                                  │  invest-platform :8790（宿主机进程/容器均可）   │
                                  │  FastAPI · star JWT 纵深防御（共享密钥本地校验）│
                                  │  MySQL(star 同实例)/SQLite + akshare + cron    │
                                  └──────────────────────────────────────────────┘
```

- **gateway 模式（默认）**：`./scripts/dev-serve.sh`（.env.dev 注入密钥/DB URL）→ star 网关 → 小程序微信一键登录，无需手填令牌
- **direct 模式（备用）**：`invest serve --lan`（静态令牌）——star 环境不可用时的独立运行形态
- 本机浏览器访问 `http://127.0.0.1:8790` 免鉴权（Web 平台不受影响）

## 二、安全模型（章程 v2.0：数据存放本人私有服务，公网化路线见 00-charter）

| 层 | 机制 |
|----|------|
| 网络面 | star 形态 invest 绑 127.0.0.1（仅网关可达）；`--lan` 才绑 0.0.0.0 |
| 鉴权链 | star 网关 JwtGlobalFilter（白名单外全拦截）→ invest TokenAuthMiddleware star 模式（PyJWT 本地校验同一 HS256 密钥，subject=memberId）——纵深防御 |
| 双模式 | `auth_mode=token`（静态令牌）/ `star`（平台 JWT）互斥；本机模式不鉴权 |
| 缓存 | HTML/接口一律 no-store（金额不进任何磁盘缓存） |
| 传输 | 当前家庭局域网 HTTP；公网化后备案域名 + HTTPS（v2.0 待办） |

密钥：`INVEST_JWT_SECRET`（**无内置默认值**，缺省全 401；2026-10-21 已全链路轮换，
长度保持 [32,48) 字节——≥48 会切 HS384 导致 invest 401）。

## 三、API 契约（/api/invest/*，P13 起前缀对齐 star 网关规范）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ping` | GET | 连通性探测（免鉴权） |
| `/overview` | GET | 总市值/浮盈/组合XIRR + 缴存进度(pension_progress) + 按品类分组持仓 + 基准估值 + 近期信号 |
| `/trades?instrument_id=&limit=` | GET | 流水列表（新→旧）+ 标的元数据 + 动作动词（申购/买入随品类） |
| `/trades` | POST | 录入（复用 Web 端 save_validated_trade 校验：超卖拒绝等） |
| `/trades/delete` | POST | 整行匹配删除（与 Web 端同一实现） |
| `/signals` | GET | 近 30 条信号 |
| `/signals/{id}/status` | POST | 确认/忽略 |
| `/pull` | POST | 触发后台拉数（与设置页同一 pulljob） |
| `/pull/status` | GET | 拉数进度与日志尾部 |
| `/instrument/{id}` | GET | 标的详情：指标+净值序列(降采样)+交易事件+信号+基金透视（P11） |
| `/nav` | POST | 手工净值录入（理财等；与 CLI `invest nav` 同落点，幂等，P11） |
| `/report/latest` | GET | 最新周报 Markdown 原文（无则 report:null，P11；**按 mtime 取新**，P12 修字典序 bug） |
| `/reports/generate` | POST | 后台生成周报 `{ai:bool}`（reportjob，AI 无 Key 自动降级，P12） |
| `/reports/status` | GET | 周报生成任务状态/日志（P12） |
| `/valuation` | GET | 指数估值表+市场温度（R1/R2：10 主流中证指数 PE 分位） |
| `/asset-curve?days=N` | GET | 组合总资产逐日市值曲线（R3，与月度统计同源） |
| `/daily-pnl?month=` | GET | 单月逐日收益（R4 日历） |
| `/diary` CRUD | GET/POST | 投资日记（R5，按日 upsert+心情标签） |
| `/annual-report?year=` | GET | 年度复盘账单（R7；账户现金单列口径） |
| `/backtest` | POST | 六策略回测（L3 已有，R 轮复用） |
| `/ocr` | POST | 图片识别录入（S1）：multipart 上传截图→本地 Vision OCR→GLM 结构化流水草稿；无 Key 降级返回原文；图片临时即用即删 |
| `/summary?months=N` | GET | 月度/年度收益统计：净投入精确自流水、浮盈变化=Δ市值−净投入（L2；contribute 只进现金流不折份额） |
| `/backtest` | POST | 六策略回测 `{start,monthly}`，曲线降采样 200 点（L3，复用 run_all_backtests） |
| `/overview` 内 `pension_progress` | — | 养老金年缴存 contributed/cap（与 build_entry_state 同口径，P12） |
| `/instruments` CRUD | GET/POST/DELETE | 标的管理（S2：删除双保护——持仓 409、yaml 种子 404） |
| `/settings/glm-key` | GET/POST | 智谱 Key 状态/保存（存 glm.local.env gitignore，即时生效，S2） |

**口径备忘（前端格式化易错点）**：
- `xirr` / `unrealized_pct`：小数（0.0504 = 5.04%），前端 ×100
- `benchmarks[].pct_5y` / `pct_all`：**已是百分数**（95.0 = 95%），前端直接显示
- `benchmarks[].drawdown_5y`：小数（-0.066），前端 ×100
- 盈亏配色：红涨绿跌（A 股习惯）

## 四、小程序工程（invest-miniapp/，同仓）

- 技术栈与 star-site-app 对齐（uni-app 3.0.0-5020420260813003 / Vue3 / TS / vite 5.2.8），**业务代码零共享**；依赖钉板见 package.json
- 页面：总览（分组持仓+指标）/ 流水（列表+录入弹层+长按删除）/ 信号（确认忽略）/ 设置（地址令牌+手动拉数）
- P11 新增：标的详情页（canvas 净值曲线+交易事件标记+基金透视+基准估值；wealth 品类带「记净值」）、周报页（markdown-lite 渲染：标题/段落/表格/列表）
- P12 新增：总览品类占比条（≥2 组有市值才显示，低饱和配色）与养老金缴存进度卡；曲线十字线触控（按住查看某日净值，读数在 canvas 下方）；周报页生成条（附 GLM 解读开关，轮询状态自动刷新）
- R1-R9 竞品借鉴十轮（v0.5）：指数估值表+市场温度（蛋卷式，10 指数）；资产总曲线+收益日历+年度账单（天天式，全部与月度统计同源口径）；投资日记（有知有行式，心情五标签）；详情页成本线；自选指数星标；全局快捷记一笔。聚焦红线：不做盘中实时估值/基金购买筛选/社区
- L1-L9 十轮产品迭代（v0.4）：录入按金额折算+净值预填；统计 tab（月度/年度盈亏）；策略回测页（六策略曲线对比+参数）；**star 提醒集成**（设置页建定投/缴存提醒→star 待办中心，前端直连 /api/reminder）；总览数据过期黄条+就地拉数；复制快照分享（转发卡片不含金额——红线）；空态三步引导+品类口径速查；缓存秒开+页内重试；流水动作筛选+关键词搜索
- tabBar 纯文字（企业内部平台风：白卡细边框、无渐变、无 emoji、无重阴影）
- AppID 复用 `wx8bb4b89c676c6df8`（与 star-site 同一测试号；真机预览两个项目二选一）

### 构建与 E2E

```bash
cd invest-miniapp
pnpm install --dangerously-allow-all-builds   # pnpm 12 不读 onlyBuiltDependencies 字段
pnpm build:mp-weixin                          # 产物 dist/release/mp-weixin（含 postbuild 守卫）
/Applications/wechatwebdevtools.app/Contents/MacOS/cli auto \
  --project $PWD/dist/release/mp-weixin --auto-port 9421
E2E_GATEWAY=http://<局域网IP>:8080 node scripts/e2e-check.js   # 注入配置→断言→截图
```

E2E 用**元素文本断言**（uni-app vue3 编译后 `page.data()` 是混淆结构，不可用）。
工程细节（401 自愈、构建守卫、工具版本锁、排障）见 [08-miniapp-engineering.md](../frontend/miniapp-engineering.md)。

## 五、已验证（2026-10-18，P12 更新）

- 后端 75 单测全绿（mp API 14 个）；E2E 14 项全 PASS（含十字线读数断言、周报后台生成真实链路）
- LAN 联调：ping 免鉴权、无 token 401、真实数据返回（市值与 snapshot 逐位一致）
- 模拟器 E2E 六项 PASS；总览/表单截图过视觉验收（期间修复分位 ×100 显示 bug）

## 六、待办（下个里程碑候选）

- [ ] 真机预览（需负责人扫码，GUI 环节）
- [ ] star 提醒依赖家庭数据（先在 star 健康平台建家庭与成员）；无家庭时优雅降级
- [x] 理财(wealth)净值在小程序端录入（P11 已做：详情页 wealth 品类「记净值」弹层 → /nav）
- [ ] 概览页净值曲线图（mp 用 canvas 或 echarts-for-weixin，暂缓——数字与表格先满足记账本诉求）
