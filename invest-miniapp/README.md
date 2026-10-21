# invest-miniapp · 个人投资管理小程序端

> invest-platform 的移动入口（uni-app + Vue3 + TS），与后端同仓（invest 单仓 monorepo 的 invest-miniapp/ 目录）。
> **登录走 star 平台**：wx.login → star 网关 `/api/auth/wx-login` → 统一 JWT；
> 业务请求经 star 网关 `/api/invest/**` 路由到 invest 微服务（Python）。
> 业务上与 star 系列完全独立，仅基础设施（登录/网关/鉴权）集成。
> 架构与 API 契约见 [invest-platform/docs/06-miniapp.md](../invest-platform/docs/06-miniapp.md)。

## 页面

- **总览**：总市值/浮动盈亏/组合 XIRR、品类占比条、养老金缴存进度，按品类分组持仓，基准估值，近期信号；点持仓行进详情
- **流水**：列表（筛选/长按删除）+ 底部弹层录入（标的/动作/日期/数量/价格/费用/备注）
- **信号**：策略信号确认/忽略（纪律工具，非收益保证）
- **标的详情**：canvas 净值曲线（期间涨跌+交易事件标记+按住查看某日净值）、指标、基准估值、基金持仓穿透；理财品种可「记净值」
- **周报**：最新周报速览（markdown-lite 轻渲染）+ 一键生成（附 GLM 解读开关，后台任务轮询）
- **设置**：接入方式（star 网关[默认] / 本机直连）、登录状态、手动拉数

## 快速开始

```bash
# 1. 启动 invest 微服务（star 形态；本仓 invest-platform/ 目录）
uv run python -m invest serve --auth star          # star JWT 纵深防御，127.0.0.1:8790

# 2. 启动 star 网关 + member（star-site-backend docker compose；网关 :8080
#    路由 /api/invest/** → host.docker.internal:8790，wx-login mock 通道默认开）

# 3. 构建小程序（本目录）
pnpm install --dangerously-allow-all-builds
pnpm build:mp-weixin

# 4. 微信开发者工具导入 dist/build/mp-weixin；设置页填网关地址（http://<LAN-IP>:8080）→ 微信一键登录
```

开发调试：`pnpm dev:mp-weixin`（watch）或 `pnpm dev:h5`（H5 经 vite 代理到网关 8080）。
本机直连模式（不走 star）：`invest serve --lan` 生成令牌，设置页切「本机直连」填地址+令牌。

## E2E

```bash
node scripts/e2e-check.js   # 注入配置→页面元素断言→截图 /tmp/invest-miniapp-shots/
```

注意：uni-app vue3 编译后 `page.data()` 返回混淆结构，断言一律用元素文本（`page.$(selector).text()`）。

## 边界与约定

- 真机需与电脑同 Wi-Fi；开发者工具勾选「不校验合法域名」（urlCheck 已在 project.config.json 关闭）
- 登录态：star JWT（720 分钟）存 storage 键 `invest_token`，401 自动清 token 重登
- AppID 暂复用测试号 `wx8bb4b89c676c6df8`（与 star-site 相同，真机预览两个项目二选一）
- 盈亏配色红涨绿跌；分位字段后端已是百分数、XIRR 是小数（易错口径见 docs/06 第三节）
- storage 键前缀 `invest_`（与其它小程序项目隔离）

[star-site-app]: ../../star-site-app
