# 08 · 前端工程指南（invest-miniapp）

> 前端专项文档：工程结构、API 层设计、构建链、UI 规范、E2E 与排障。
> 全仓架构见 [07-architecture.md](../architecture.md)；API 端点契约见 [06-miniapp.md](../backend/api-contract.md)。

## 1. 技术栈与定位

- **uni-app 3.0（5020420260813003）+ Vue3 `<script setup>` + TypeScript + vite 5.2.8**，
  与 star-site-app 技术栈对齐但**业务代码零共享**；依赖版本钉板见 `package.json`
- 小程序是 invest-platform 的**移动入口**：领域逻辑（账本/指标/策略）全在 Python 端，
  前端只做展示与录入——**所有操作在微信小程序完成，不存在 PC 端**（用户产品原则）
- 唯一形态差异：H5 调试端（`pnpm dev:h5`，vite 代理 `/api` → invest:8792 同源免跨域）
  仅供开发调试，不是产品端

## 2. 目录结构

```
invest-miniapp/
├── src/
│   ├── pages/            # 13 个页面（5 tab + 8 功能页，清单见 07 §2.1）
│   ├── api/
│   │   ├── client.ts     # 请求封装（401 自愈在此）
│   │   ├── auth.ts       # star 静默登录（单飞）+ 重登钩子注册
│   │   ├── config.ts     # 双模式配置 storage（invest_ 前缀键）
│   │   ├── invest.ts     # /api/invest 业务端点
│   │   └── star.ts       # star family/reminder 直连（L4 提醒）
│   ├── types/            # 后端 VO 类型
│   └── pages.json        # 路由与 tabBar（纯文字 tab，企业内部平台风）
├── scripts/
│   ├── postbuild-wxss.js # wxss 多行规范化 + 反斜杠守卫（见 §5）
│   └── e2e-check.js      # automator E2E（14 项断言 + 截图）
└── dist/release/mp-weixin/   # 构建产物（UNI_OUTPUT_DIR；开发者工具导入此路径）
```

## 3. API 层三件套（前端最核心的机制）

### 3.1 client.ts —— 请求封装 + 401 自愈

```
request(opts)
  ├─ getServer() 为空 → 抛「未配置服务器地址」（首装/清缓存后，到「我的」配置）
  ├─ 正常：uni.request + Bearer token
  └─ 收到 401（gateway 模式且非 /api/auth/**）：
       清 token → registerRelogin 钩子（auth.ts 注册，防循环依赖）
       → silentWxLogin 单飞重登 → 原请求重试一次
```

- 豁免规则：登录端点自身（防钩子等待自己的死锁）；direct 模式（静态令牌重试无意义）
- `rawPath: true` 用于网关裸路径（如 `/api/auth/**`），否则自动拼 `/api/invest` 前缀
- 错误统一 `ApiError(status, message)`；页面用 `showApiError` 弹 toast

### 3.2 auth.ts —— 静默登录单飞

- `wx.login code → 网关 /api/auth/wx-login → star JWT → storage(invest_token)`
- **单飞**：模块级 in-flight promise，并发调用共享同一次登录（教训：登录与首拉并发
  曾导致 401 重试链在异步嵌套中丢失 promise）
- `ensureLogin(timeout=8s)`：页面 `onShow` 首拉前 await；token 存在直接放行
  （有效性交给 client 的 401 自愈兜底）

### 3.3 config.ts —— 双模式与 storage 键

| 键 | 含义 |
|----|------|
| `invest_auth_mode` | `gateway`（默认，star 网关+微信登录）/ `direct`（LAN+静态令牌） |
| `invest_server` | gateway=网关地址；direct=invest 地址 |
| `invest_token` | star JWT / LAN 静态令牌（切换模式时清除，两模式令牌不通用） |
| `invest_member` | gateway 登录后的成员信息 JSON（「我的」页昵称） |

## 4. 构建链

```bash
pnpm install --dangerously-allow-all-builds   # pnpm 12 不读 onlyBuiltDependencies
pnpm build:mp-weixin    # = UNI_OUTPUT_DIR=dist/release/mp-weixin uni build -p mp-weixin
                        #   && node scripts/postbuild-wxss.js
```

- **产物路径是 `dist/release/mp-weixin`**（曾用 dist/build，2026-10 迁移后持久新路径；
  开发者工具导入/挂载都用这个路径）
- postbuild-wxss.js 两个职责：
  1. 多行规范化——超长单行 wxss 会触发工具误报列位置
  2. **反斜杠守卫**——WXSS 不支持 `\XXXX` unicode 转义；Vue 编译器会把中文类名转成
     `.\8d2a\5a6a`（合法 CSS 但 WXSS 直接编译错误，且**静默炸掉 appLaunch**：白屏 +
     页面栈空 + automator 全灭三连锁）。任何 wxss 含 `\` 构建即失败，类名一律 ASCII

## 5. UI 规范（企业内部平台风，负责人审美红线）

- 白卡 + 1rpx 细边框 + 12rpx 圆角；主色 `#1652a8`，文字 `#1d2129`/次级 `#86909c`
- **拒绝 AI 味**：无渐变、无 emoji、无重阴影、无花哨配色
- 红涨绿跌（A 股习惯）；tabBar 纯文字
- 金额格式化带千分位；口径易错点见 06 §三（pct 已是百分数、xirr 是小数）

## 6. E2E 与开发者工具

```bash
# 服务端口被重置时（更新/删缓存/换版本后）无人值守重开：
pkill -9 -f wechat; printf 'y\n' | /Applications/wechatwebdevtools.app/Contents/MacOS/cli islogin

# 挂自动化端口并跑 E2E（网关地址经环境变量注入，公开仓不落内网 IP）
/Applications/wechatwebdevtools.app/Contents/MacOS/cli auto \
  --project $PWD/dist/release/mp-weixin --auto-port 9421
E2E_GATEWAY=http://<局域网IP>:8080 node scripts/e2e-check.js
```

- E2E 用**元素文本断言**（uni-app vue3 编译后 `page.data()` 是混淆结构，不可用）
- 工具版本锁：基础库 **3.8.0**（真开关在产物的 `project.private.config.json`，优先级
  高于 project.config.json）、automator **0.12.1**（0.13.0 有连接回归）
- 重建 dist 后需彻底重启工具再挂项目（否则报「项目根目录未找到 app.json」）
- 完整踩坑沉淀见 [07-architecture.md §6](../architecture.md)

## 7. 迭代史索引（详录见 git log 与各期 commit）

| 轮次 | 主题 | 代表特性 |
|------|------|----------|
| P9-P13 | 品类扩展 + star 集成 | 五品类、LAN 令牌、详情页、star 网关接入 |
| L1-L10 | 个人可用性十轮 | 按金额录入、统计 tab、回测、提醒、缓存秒开 |
| R1-R10 | 竞品借鉴十轮 | 估值表/温度计、资产曲线/日历、日记、年度账单 |
| S1-S2 | OCR + 标的管理 | Vision+GLM 双轨识别、小程序 CRUD |
| v0.6 | 信号与体验 | 立即评估、PE 分位带、401 自愈 |
| 公网化 | v2.0 第一梯队 | 「我的」模块、MySQL 双后端、密钥轮换 |
