# S06 · 页面 UX 模式规范（Spec）

> 优先级 P1 · 状态：**已实现（验收记录待补）**
> 原则：每个页面必须覆盖加载/空/错/重试四态——缺一态就是 bug。

## Problem

页面间 UX 不一致——有的有 loading 有的没有，有的有空态有的没有。
用户在等待时不知道系统是否在工作，出错时不知道该怎么做。

## 四态规范（每个页面必须实现）

### 1. 加载态（Loading）

```
首次进入：显示骨架屏（占位灰色块，非空白）
刷新数据：顶部细进度条或 "刷新中..." 文字
按钮操作：按钮 loading 态（防重复点击）
```

### 2. 空态（Empty）

```
无数据时：显示插图 + 引导文案 + 操作按钮
例："还没有交易记录" + "记第一笔" 按钮
禁止：纯空白页面
```

### 3. 错误态（Error）

```
请求失败：ErrorCard 组件（图标 + 描述 + 重试按钮）
网络错误："网络异常，请检查连接"
服务错误："服务暂时不可用"
```

### 4. 重试态（Retry）

```
ErrorCard 上的"重试"按钮 → 重新发起请求
请求中按钮变为 loading → 防重复点击
成功后自动切换到正常态
```

## 各页面四态覆盖现状与目标

| 页面 | loading | empty | error | retry | 目标 |
|---|---|---|---|---|---|
| overview | ✅ | ✅ | ✅ | ✅ | 保持 |
| trades | ✅ | ✅ | ✅ | ❌ | **补 retry** |
| signals | ✅ | ✅ | ✅ | ❌ | **补 retry** |
| settings | ❌ | ✅ | ✅ | ❌ | **补 loading + retry** |
| summary | ✅ | ✅ | ✅ | ❌ | **补 retry** |
| backtest | ❌ | ✅ | ❌ | ❌ | **补 loading + error + retry** |
| instrument | ✅ | ❌ | ❌ | ❌ | **补 empty + error + retry** |
| report | ✅ | ✅ | ✅ | ❌ | **补 retry** |
| valuation | ✅ | ❌ | ❌ | ❌ | **补 empty + error + retry** |
| diary | ✅ | ✅ | ❌ | ❌ | **补 error + retry** |
| annual | ✅ | ✅ | ❌ | ❌ | **补 error + retry** |

## Acceptance Criteria

### AC-1 全页面四态覆盖

- **GIVEN** 小程序的任意页面
- **WHEN** 分别触发：首次加载 / 无数据 / 网络断 / 点击重试
- **THEN** 四种状态都有对应的 UI 反馈（骨架屏/空态/错误卡/重试按钮）

### AC-2 下拉刷新

- **GIVEN** 任意 Tab 页
- **WHEN** 用户下拉
- **THEN** 触发数据刷新 + 顶部显示刷新动画
- **AND** 刷新完成后动画消失

### AC-3 操作反馈

- **GIVEN** 用户点击"记一笔"提交
- **WHEN** 请求发出
- **THEN** 按钮变为 loading 态（不可再点击）
- **AND** 成功后 toast "已保存" + 按钮恢复
- **AND** 失败后 toast 错误信息 + 按钮恢复

## 统一组件规范

```
ErrorCard.vue（全局组件）：
  <view class="error-card">
    <image src="/static/error.svg" />
    <text class="error-title">{{title}}</text>
    <text class="error-desc">{{description}}</text>
    <button @tap="$emit('retry')" :loading="loading">重试</button>
  </view>

EmptyState.vue（全局组件）：
  <view class="empty-state">
    <image src="/static/empty.svg" />
    <text>{{message}}</text>
    <button v-if="action" @tap="$emit('action')">{{actionText}}</button>
  </view>
```

## Out of Scope

- 骨架屏的具体设计稿（按现有 Tabler 风格灰色块即可）
- 动画细节（过渡时长等，属视觉调优）

## 验收记录

（实现后填写）
