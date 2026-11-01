# S03 · 全局错误处理与自愈（Spec）

> 优先级 P0 · 状态：**Spec 待实现** · 前置：无
> 原则：任何输入不崩溃、任何依赖不挂死、任何错误有出路。

## Problem

当前后端无全局异常处理器——任何未预期异常直接返回 500 裸堆栈给小程序端，
用户看到"系统繁忙"但无法自愈。小程序端 5 个页面无重试按钮，出错后用户
只能杀掉重进。

## User Stories

- **US-1**：作为用户，我在地铁里网络断了一下，回来刷新页面能自动重试，不需要杀小程序
- **US-2**：作为用户，我输入了非法数据（如负数份额），系统给出友好提示而非 500
- **US-3**：作为用户，外部行情源挂了，我依然能看到本地缓存的数据和"数据源异常"提示

## Acceptance Criteria

### AC-1 后端全局异常兜底

- **GIVEN** 任何 API 端点抛出未预期异常
- **WHEN** 请求到达 FastAPI
- **THEN** 返回 `{"error": "<友好消息>", "detail": "<error_type>"}` + HTTP 500
- **AND** 响应头 `X-Error-Type` 标注异常类名（排障用）
- **AND** 日志记录完整堆栈 + traceId

### AC-2 后端输入校验

- **GIVEN** POST /api/invest/trades 请求的 quantity 为负数或非数字
- **WHEN** 后端处理请求
- **THEN** 返回 422 + `{"error": "份额必须为正数"}`（不是裸 500）

### AC-3 小程序网络错误重试

- **GIVEN** 用户在 overview 页
- **WHEN** API 请求因网络超时失败
- **THEN** 页面显示"网络异常，点击重试"卡片（非空白页）
- **AND** 点击重试按钮重新请求
- **AND** 重试成功后正常显示数据

### AC-4 小程序 401 自愈重登

- **GIVEN** 用户已登录（gateway 模式）
- **WHEN** token 过期导致 API 返回 401
- **THEN** 自动静默重登（复用 wx.login 单飞）
- **AND** 重登成功后自动重试原请求
- **AND** 用户全程无感知（无弹窗）
- **AND** 重登失败时跳转设置页（带提示）

### AC-5 外部数据源降级

- **GIVEN** akshare 行情源超时
- **WHEN** 用户查看标的详情
- **THEN** 返回最近缓存的净值数据 + `"stale": true` 标记
- **AND** 前端显示"数据延迟"角标

## Out of Scope

- 分布式追踪（traceId 透传已在 S02 后端交付）
- 前端离线模式（P2+ 再议）
- 前端骨架屏（属 S06 UX 模式规范）

## 实现要点

1. FastAPI `@app.exception_handler(Exception)` 全局兜底
2. Pydantic `ValidationError` handler → 422 友好消息
3. 小程序端统一 ErrorCard 组件 + retry 事件
4. `src/api/client.ts` 已有 401 自愈逻辑（确认覆盖所有端点）
5. akshare 超时用 `concurrent.futures.ThreadPoolExecutor` + timeout 参数

## 验收记录

（实现后填写）
