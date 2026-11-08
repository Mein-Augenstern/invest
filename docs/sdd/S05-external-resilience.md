# S05 · 外部 API 韧性（Spec）

> 优先级 P1 · 状态：**已实现（验收记录待补）**
> 原则：外部依赖不阻塞、超时有兜底、降级有缓存。

## Problem

akshare 行情/净值源无超时和重试——网络抖动时 API 请求挂死（用户看到无限加载）。
深夜东财接口不稳（今天验证 159928 拉数失败），需要多源兜底 + 超时降级。

## User Stories

- **US-1**：作为用户，我在地铁里刷新总览，行情源超时了，我看到缓存数据+"数据延迟"提示
- **US-2**：作为用户，我连续快速下拉刷新 3 次，不会发出 3 次行情请求（防抖/节流）
- **US-3**：作为用户，我在标的管理页录入新基金代码，系统自动验证可拉取行情

## Acceptance Criteria

### AC-1 行情拉取超时

- **GIVEN** akshare 接口 5 秒无响应
- **WHEN** 用户请求标的详情
- **THEN** 返回缓存的最近数据 + `stale: true`
- **AND** 总耗时不超过 6 秒（5s 超时 + 1s 缓存读取）

### AC-2 多源兜底

- **GIVEN** 东财（primary）超时
- **WHEN** 拉取净值
- **THEN** 自动切换到新浪（secondary）
- **AND** 新浪成功则返回新浪数据 + `"source": "sina"`
- **AND** 两源都失败则返回缓存

### AC-3 前端防抖

- **GIVEN** 用户在总览页连续下拉刷新 3 次
- **WHEN** 3 次刷新间隔 < 2 秒
- **THEN** 只发出 1 次行情请求（后端防抖）
- **AND** 返回同一份结果

### AC-4 拉数任务幂等

- **GIVEN** 用户触发"拉取最新数据"
- **WHEN** 上一次拉数任务仍在执行中
- **THEN** 返回"正在拉取中"（不重复启动）
- **AND** 前端轮询状态直到完成

## Out of Scope

- Kafka/消息队列异步拉数（P3+ 再议）
- CDN 加速
- 自建行情聚合服务

## 实现要点

1. `DataProvider` 协议增加 `timeout` 和 `fallback_provider` 参数
2. `akshare_provider.py` 用 `ThreadPoolExecutor + future.result(timeout=5)` 包裹
3. 缓存层：SQLite series 表已是缓存（查最近一条 + stale 标记）
4. 防抖：FastAPI middleware 按 `instrument_id` 维度做 2 秒去重

## 验收记录

（实现后填写）
