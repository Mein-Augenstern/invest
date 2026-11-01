# S01 · 真实组合配置与数据归一（Spec · 2026-11-01）

> 状态：**Spec 完成待实现** · 优先级 P0 · 依赖：用户输入（持仓清单 + AppSecret）
> 前置：G2 公网化已收官（docs/tech/g2-tunnel-runbook.md），当前跑 portfolio.example.yaml。

## 1. 问题陈述

### 1.1 现状（两个"假"）

| 维度 | 现状 | 影响 |
|---|---|---|
| **组合数据** | `portfolio.example.yaml`（示例标的：consumer50_etf 等） | 总览/信号/统计全是假数据——用户真实持仓（红利联接Y/消费50等）未配置 |
| **用户身份** | mock 登录通道（WX_MP_SECRET 未配置） | 每次登录生成新 memberId（幽灵账号 16~19 已产生）；数据不按 openid 归一 |

### 1.2 目标状态

| 维度 | 目标 | 验收 |
|---|---|---|
| **组合数据** | `config/portfolio.local.yaml`（真实持仓） | 总览显示真实标的+市值；信号基于真实 PE 分位 |
| **用户身份** | 正式号 AppSecret + code2Session | 同一微信重登 → 同一 memberId；数据跟人走 |

## 2. 需求分解

### S01-A：真实组合配置

**用户输入**（一次性，5 分钟）：
- 每个标的的：代码（场内 ETF/场外基金）、名称、品类（stock/fund/bond/wealth）
- 当前持仓（份额，从券商/基金 App 截图或手动填写）
- 净值来源（auto=akshare 四级兜底 / manual=手工录入）

**系统行为**：
1. `config/portfolio.local.yaml` 按上述输入生成（gitignore，真实持仓不入库）
2. `invest pull-data` 拉取所有标的行情/净值入 SQLite
3. `invest snapshot` 生成真实持仓快照（市值/成本/盈亏）
4. 小程序总览页显示真实数据（不再有"示例"水印）

**验收用例**：
- [ ] AC-A1：`portfolio.local.yaml` 含 ≥3 个真实标的
- [ ] AC-A2：`invest pull-data` 全部成功（selfcheck 0 FAIL）
- [ ] AC-A3：总览页市值 = 手动计算值（份额 × 最新净值）
- [ ] AC-A4：信号页显示真实 PE 分位带（非空态）

### S01-B：AppSecret 配置与数据归一

**用户输入**（一次性，10 分钟）：
1. mp 后台 → 开发设置 → AppSecret 行 → 生成（需身份确认扫码）
2. 复制 AppSecret 值发给开发者

**系统行为**：
1. `.env.dev` 新增 `WX_MP_SECRET=<value>`
2. `docker-serve.sh` 透传给 member 容器（`WX_MP_SECRET` 环境变量）
3. member 的 `WxSessionGateway` 从 mock 通道切到真实 code2Session：
   - `wx.login()` 拿 code → 后端调微信 API `jscode2session` → 换取 openid
   - openid 与 memberId 绑定（首次登录静默注册，后续登录复用）
4. invest 的 owner 字段取 memberId（当前 mock 下每次是新值）

**验收用例**：
- [ ] AC-B1：登录后 memberId 稳定（杀小程序重登 → 同一 memberId）
- [ ] AC-B2：member 日志无 `mock 通道` 字样
- [ ] AC-B3：trades.csv 数据与 memberId 关联（owner 隔离前置）
- [ ] AC-B4：不同微信号登录 → 不同 memberId（多用户区分）

### S01-C：部署脚本集成

**系统行为**：
1. `docker-serve.sh` 读 `.env.dev` 的 `WX_MP_SECRET` 并透传到 member 容器
2. `docker-serve.sh` 挂载 `config/portfolio.local.yaml`（若存在）为只读
3. 部署验证脚本 `scripts/g2-regression.sh` 增加 B5 用例（memberId 稳定性）

## 3. 实现计划

| 步骤 | 内容 | 依赖 | 预计 |
|---|---|---|---|
| 1 | 生成 portfolio 模板（用户填空即用） | 无 | 30 min |
| 2 | docker-serve.sh 集成 WX_MP_SECRET + portfolio 挂载 | 无 | 15 min |
| 3 | 回归脚本 B5 用例（memberId 稳定） | 步骤 2 | 15 min |
| 4 | **[用户]** 填真实持仓 + 生成 AppSecret | 步骤 1 | 15 min |
| 5 | **[开发者]** 配置 + 重启 + 端到端验证 | 步骤 2+4 | 30 min |

## 4. 边界与约束

- portfolio.local.yaml 绝不入 git（.gitignore 已配）
- AppSecret 只经 .env.dev 注入（不落代码/脚本）
- mock 通道保留为 fallback（WX_MP_SECRET 未配置时自动降级，日志打 WARN）
- 本 Spec 不涉及 O1 多用户 owner 隔离改造（那是独立 Spec S02）
