# S07 · 导航与信息架构（Spec）

> 优先级 P2 · 状态：**已实现（验收记录待补）**
> 原则：用户 3 秒内能到达任何常用功能，不迷路。

## Problem

当前 5 个 Tab（览表/统计/流水/信号/我的）覆盖核心，但 8 个二级页面
（summary/backtest/instrument/report/valuation/diary/annual/ocr）
入口分散——有的从总览卡片进、有的从"我的"进，新用户不知道去哪找。

## 信息架构

```
Tab 1: 总览（overview）       ← 首页，看全局
  ├─ 记一笔（弹层）
  ├─ 持仓卡片 → 标的详情（instrument）
  └─ 缴存进度卡

Tab 2: 统计（summary）        ← 看数据
  ├─ 资产曲线 → 估值分析（valuation）
  ├─ 月度盈亏 → 月报（report）
  └─ 年度总结（annual）

Tab 3: 流水（trades）         ← 记账
  ├─ 筛选/搜索
  └─ OCR 录入 → 标的识别（ocr → instruments）

Tab 4: 信号（signals）        ← 纪律
  ├─ 当前信号
  ├─ 纸面交易
  └─ 回测（backtest）

Tab 5: 我的（settings）       ← 配置
  ├─ 服务器设置
  ├─ GLM API Key
  ├─ 标的管理（instruments）
  └─ 投资日记（diary）
```

## Acceptance Criteria

### AC-1 TabBar 不超 5 个

- **GIVEN** 小程序底部 Tab
- **WHEN** 加载完成
- **THEN** Tab 数量 ≤ 5（当前正好 5）

### AC-2 二级页面可达性

- **GIVEN** 任意二级页面（如 annual）
- **WHEN** 从首页出发
- **THEN** 最多 2 次点击可达（overview → 统计 → annual = 2 次）

### AC-3 返回导航

- **GIVEN** 用户从总览进入标的详情
- **WHEN** 点击返回
- **THEN** 回到总览（不是"我的"）

### AC-4 页面标题

- **GIVEN** 任意页面
- **WHEN** 加载完成
- **THEN** 导航栏标题正确显示页面名称（不是空白或"undefined"）

## Out of Scope

- 自定义导航栏（用微信原生）
- 页面转场动画
- 深层链接/分享路径

## 验收记录

（实现后填写）
