# Web 管理平台架构（v0.2，2026-09-05）

## 总览

本地单用户 Web 管理平台（`invest serve` → http://127.0.0.1:8790），
FastAPI + Jinja2 服务端渲染 + Tabler 布局壳；CLI 与 Web 共用同一领域层（reporting.py 唯一实现）。

```
浏览器 ── 127.0.0.1:8790 ── uvicorn
                              ├─ webapp/routes_pages.py（6页, 同步 def）
                              ├─ webapp/routes_api.py（JSON API, 变更全 POST）
                              ├─ webapp/views.py ──→ reporting.py ──→ 领域层(data/ledger/metrics/strategy)
                              ├─ pulljob.py ──→ pipeline.run_pull（后台线程拉数）
                              └─ templates(Jinja2) + static(Tabler vendor + invest-charts.js)
```

## 分层铁律（code review 机械检查项）

1. `webapp/` 内**禁止**直接 import pandas/metrics/ledger 做计算——一切视图数据走 `reporting.py`
   （表单校验/落盘走 `ledger.trades` 的写入函数，属领域层自身入口）。
2. 页面路由一律**同步 `def`**（pandas 组装丢线程池）；`async def` 里跑 pandas 会卡事件循环。
3. 读写分离：页面刷新只读（`recent_signals` 等只读查询）；"评估信号/生成周报/拉数"是显式动作
   （按钮 → POST），刷新页面永不产生写副作用。
4. 格式化归渲染层：视图模型是数值/None；千分位与百分比在 Jinja2 filter（`fmt`/`pct`）或 markdown 渲染器。

## 路由与 API

| 页面 | 路径 | 数据来源 |
|---|---|---|
| 总览 | `/` | build_portfolio_view + holdings图表 + 信号摘要(5) |
| 持仓 | `/positions` | 持仓表 + 基准估值表 + 对比图/PE历史图 |
| 流水 | `/trades` | build_entry_state（表单+增删+缴存进度） |
| 信号 | `/signals` | recent_signals(20) + 确认/忽略/立即评估 |
| 报告 | `/reports`，`/reports/view/{name}` | data/reports 列表 + 生成（GLM 可选） |
| 设置 | `/settings` | 策略参数只读 + 手动拉数(后台) + 环境 |

| API | 方法 | 说明 |
|---|---|---|
| `/api/state` | GET | 流水页状态 |
| `/api/trades` | POST | 新增流水（校验+落盘同锁；422 校验失败） |
| `/api/trades/delete` | POST | 整行内容匹配删除（409 不匹配） |
| `/api/signals/evaluate` | POST | 评估+落库信号 |
| `/api/signals/{id}/status` | POST | 状态流转（建议/已确认/已忽略） |
| `/api/reports/generate` | POST | 生成周报 `{ai: bool}` |
| `/api/pull`、`/api/pull/status` | POST/GET | 触发后台拉数 / 轮询状态与日志 |

## 安全模型

- **仅绑定 127.0.0.1**；Host 白名单中间件（防 DNS 重绑定），白名单是 `create_app(allowed_hosts=...)` 参数
  （测试传 `testserver`）。
- 所有变更操作只走 **JSON POST**；服务不发 CORS 头 → 浏览器预检必失败 → 恶意网页无法跨站调用。
- HTML/接口响应 `no-store`（持仓金额不进磁盘缓存）；`/static/vendor/*` immutable 长缓存，其余 no-cache。
- 报告查看路由文件名白名单 `^[A-Za-z0-9_-]+\.md$`（防路径穿越）。
- 无登录（本机单用户）；如需暴露局域网属于红线变更，需先过章程评审。

## Vendoring 登记

| 资产 | 版本 | 来源 | 取用范围 |
|---|---|---|---|
| Tabler | **1.4.0** | https://cdn.jsdelivr.net/npm/@tabler/core@1.4.0/dist/css/tabler.min.css | **仅 tabler.min.css**（536KB，全部 url() 为内联 data URI，无外链）；未引入 tabler.min.js 与 vendors 包 |
| License | MIT | https://raw.githubusercontent.com/tabler/main/main/LICENSE | `static/vendor/tabler/LICENSE` |

图表视觉体系（.viz-scope 命名空间的 --s1/--s2/明暗双模式 token，已过 CVD 与对比度验证）
**不映射 Tabler 主题变量**，升级 Tabler 不影响已验证配色。

## 依赖（新增3+1，理由）

fastapi + uvicorn + jinja2（Web 管理平台的服务端渲染与路由，用户确认的升级需求）；
dev 组 httpx（FastAPI TestClient 硬依赖）。刻意不用 `fastapi[standard]`（拖入 watchfiles/websockets 等8包，
违反依赖最小化）。表单走 fetch+JSON，不需要 python-multipart。

## 已退役

- `invest dashboard`（静态HTML看板）：web 总览/持仓页已对等，避免双轨维护。
- `invest entry`（标准库录入服务）：功能并入 `/trades` 页；命令保留 deprecated 提示，下版本移除。
