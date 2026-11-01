# S02 · 策略引擎 v1（Spec · 2026-11-01）

> 状态：**Spec 完成待实现** · 优先级 P1（路线图 P3 遗留） · 依赖：S01（真实数据）
> 前置：估值指标（P2）已完成（PE 分位/股息率/回撤/相关性），数据底座（P1）已稳定。

## 1. 问题陈述

### 现状
- 估值指标已有（PE 5年/全历史分位、股息率、最大回撤、相关性矩阵）
- 信号输出仅有"PE 分位落区 → 建议加减仓"的简单规则（v0.6 体验版）
- **策略引擎缺位**：无规则可配置、无纸面模拟跟踪、无信号历史回溯

### 目标
- **规则化信号引擎**：多维度规则（估值分位+趋势+风险）→ 综合信号（buy/hold/sell/rebalance）
- **纸面模拟跟踪**：信号触发 → 记录虚拟操作 → 跟踪后续表现（非真实交易）
- **信号历史**：每个信号的生命周期（生成→确认/忽略→结果），支持回看"当时说了什么"

## 2. 需求分解

### S02-A：规则引擎

**规则模型**：
```yaml
# config/strategy.local.yaml（用户可自定义）
rules:
  - id: pe-percentile-band
    name: PE 分位带
    enabled: true
    conditions:
      - metric: pe_percentile_5y
        operator: lt
        value: 20
    signal: buy          # buy/hold/sell/rebalance
    weight: 0.4          # 权重（多规则综合）
    note: "PE 5年分位 <20%，历史低估区间"

  - id: trend-ma-cross
    name: 均线趋势
    enabled: true
    conditions:
      - metric: close
        transform: sma_200   # 200日均线
        operator: gt
        value: current_close
    signal: hold
    weight: 0.3

  - id: drawdown-guard
    name: 回撤保护
    enabled: true
    conditions:
      - metric: max_drawdown_1y
        operator: gt
        value: 0.15        # 15%
    signal: rebalance
    weight: 0.3
    note: "近一年回撤超15%，触发再平衡检查"
```

**引擎行为**：
1. 加载规则 → 对每个标的评估所有启用规则
2. 加权综合 → 最终信号（buy/hold/sell/rebalance/ignore）
3. 输出信号卡片（含各规则命中明细 + 综合权重）

### S02-B：纸面模拟跟踪

**数据模型**：
```
paper_trades 表：
  id, signal_id, instrument_id, action, quantity, price_at_signal,
  created_at, closed_at, close_price, return_pct, status(open/closed/expired)
```

**行为**：
1. 信号确认 → 生成纸面交易（虚拟买入/卖出）
2. 定时拉数 → 更新最新价格 → 计算浮盈
3. 信号关闭（手动/过期）→ 计算最终收益
4. 页面展示：纸面组合 vs 实际组合对比

### S02-C：信号生命周期

```
信号状态机：
  generated → confirmed（用户确认） → paper_trade_open → paper_trade_closed
           → ignored（用户忽略）   → expired（7天未操作）
```

**API 契约**：
| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/invest/signals` | GET | 当前信号列表（含生命周期状态+纸面交易状态） |
| `/api/invest/signals/evaluate` | POST | 立即评估（拉最新数据跑规则） |
| `/api/invest/signals/{id}/confirm` | POST | 确认信号 → 开纸面交易 |
| `/api/invest/signals/{id}/ignore` | POST | 忽略信号 |
| `/api/invest/signals/history` | GET | 历史信号（含已关闭的纸面交易收益） |

### S02-D：小程序页面

**信号页升级**：
- 信号卡片：综合信号 + 各规则命中明细（展开/收起）
- 操作按钮：确认（开纸面交易）/ 忽略
- 纸面交易标签页：持仓中 / 已关闭（含收益%）
- 策略说明弹窗：当前启用的规则列表 + 各规则近期命中率

## 3. 验收用例

- [ ] AC-1：`strategy.local.yaml` 含 ≥2 条规则，`invest signals --confirm` 输出综合信号
- [ ] AC-2：信号确认后 paper_trades 表有记录（open 状态）
- [ ] AC-3：7 天后信号自动过期（状态 → expired）
- [ ] AC-4：纸面交易关闭后 return_pct 计算正确
- [ ] AC-5：小程序信号页显示规则明细（展开）
- [ ] AC-6：信号历史页显示已关闭交易（含收益）

## 4. 实现计划

| 步骤 | 内容 | 预计 |
|---|---|---|
| 1 | 规则模型 + YAML 加载 + 评估引擎（核心） | 2h |
| 2 | 信号生命周期状态机 + 存储 | 1h |
| 3 | 纸面交易生成/跟踪/关闭 | 1h |
| 4 | API 5 端点 | 1h |
| 5 | 小程序信号页升级 | 1.5h |
| 6 | 单测 + E2E | 1h |
| 7 | 回归脚本 S02 用例 | 30 min |

## 5. 边界与约束

- **不自动交易**：纸面模拟仅记录，不产生真实交易（章程红线）
- **不预测**：信号是"规则命中→纪律建议"，不是"预测涨跌"（章程红线）
- 策略配置不入 git（strategy.local.yaml）
- 纸面交易数据在 invest_dev 库（同现有）
