# S04 · 数据完整性与并发安全（Spec）

> 优先级 P0 · 状态：**已实现（验收记录待补）**
> 原则：任何操作不丢数据、任何并发不冲突、任何崩溃可恢复。

## Problem

trades.csv 并发写入有 RLock 保护，但 MySQL/SQLite 双后端的 signals 表、
paper_trades 表的并发保护依赖数据库自身——未做应用层去重/冲突检测。
用户手动编辑 trades.csv 后可能导致 ID 冲突或持仓计算异常。

## User Stories

- **US-1**：作为用户，我和家人同时在小程序记了一笔，两笔都保存成功不丢
- **US-2**：作为用户，我编辑了 trades.csv 后重新打开小程序，不会崩溃
- **US-3**：作为用户，我误操作删了一笔交易，能在 5 秒内撤销

## Acceptance Criteria

### AC-1 并发写入不丢

- **GIVEN** 两个并发 POST /api/invest/trades 请求（不同用户）
- **WHEN** 同时到达后端
- **THEN** 两笔都成功保存（响应均 200）
- **AND** GET /api/invest/trades 返回两条记录

### AC-2 文件级数据校验

- **GIVEN** trades.csv 被外部编辑导致某行缺列
- **WHEN** 小程序请求流水列表
- **THEN** 跳过损坏行（不崩溃）
- **AND** 日志记录损坏行号和原因
- **AND** 其余正常行正常返回

### AC-3 卖出不超持仓

- **GIVEN** 某标的当前持仓 1000 股
- **WHEN** POST 卖出 1500 股
- **THEN** 返回 422 + "卖出份额超过持仓（当前 1000）"
- **AND** 持仓不变

### AC-4 事务原子性（纸面交易）

- **GIVEN** 用户确认信号 → 开纸面交易 → 同时关闭另一笔
- **WHEN** 操作过程中连接断开
- **THEN** 要么全部完成，要么全部回滚（无半完成状态）

### AC-5 数据备份恢复

- **GIVEN** 用户选择"导出备份"
- **WHEN** 点击导出
- **THEN** 生成 zip 包（trades.csv + invest.db + config/portfolio.local.yaml）
- **AND** 可通过"导入备份"完整恢复

## Out of Scope

- 多用户 owner 隔离（属 O1 白名单开放 Spec）
- 实时双向同步（WebSocket push）
- 区块链级不可篡改

## 实现要点

1. `save_validated_trade` 已有 RLock（确认 MySQL 后端同样生效）
2. `load_trades` 增加行级 try/except（跳过损坏行 + warn 日志）
3. 卖出校验已在 `validate_trade` 实现（确认覆盖所有入口）
4. SQLite WAL mode（已设置，确认）+ MySQL 事务隔离级别 READ COMMITTED
5. 备份导出：FastAPI StreamingResponse + zipfile

## 验收记录

（实现后填写）
