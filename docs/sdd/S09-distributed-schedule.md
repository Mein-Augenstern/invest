# S09 · 分布式定时拉数（Spec）

> 优先级 P0 · 状态：**已实现（2026-11-02，tests/test_s09_scheduler.py 15/15，全量 169/169）**
> 原则：分布式场景下定时任务恰一执行；数据自动新鲜；信号自动评估。

## Problem

当前拉数（行情/净值→SQLite）纯手动（CLI/API/小程序按钮），无定时任务。
分布式部署时每实例各跑 cron 会导致重复拉数、竞态写入。

## 方案选型

| 方案 | 适用场景 | 优劣 |
|---|---|---|
| **A. DB 分布式锁 + APScheduler**（推荐） | 1~5 实例，个人/小团队 | ✅ 零新基础设施（复用 starsite_lock 表）；❌ 无管理界面 |
| B. XXL-JOB | 企业级，需要 cron 管理/重试/告警 | ✅ 功能全、中文生态；❌ 需额外部署 admin 服务 |
| C. SchedulerX（蚂蚁/阿里云） | 阿里云生态，商业产品 | ✅ 免运维、秒级调度；❌ 商业依赖 |
| D. Redis SET NX + TTL | 已有 Redis | ✅ 性能好；❌ 主从切换可能丢锁（RedLock 争议） |

**选 A**：复用 starsite-lock 组件建的 `starsite_lock` 表（MySQL），Python 直连实现
与 Java 版同语义的原子争锁——零新部署，设计哲学对齐（store-side 原子 UPDATE）。

## 分布式互斥设计

```
多实例同时触发定时（20:00）
  ├─ 实例 A：原子 UPDATE starsite_lock SET locked_by='A', locked_until=+30min
  │   WHERE lock_name='invest-pull' AND (locked_until IS NULL OR locked_until < NOW())
  │   → 影响行数 > 0 = 获得锁 → 执行拉数 + 评估信号 → 释放
  ├─ 实例 B：同一 UPDATE → 影响行数 = 0（A 已持锁）→ 静默跳过
  └─ 实例 A 崩溃 → locked_until 过期（30min 后）→ B/C 下轮接管
```

## Acceptance Criteria

### AC-1 定时拉数恰一执行

- **GIVEN** 2 个 invest 实例同时运行，均配置 20:00 定时拉数
- **WHEN** 定时触发
- **THEN** 仅 1 个实例执行拉数（另 1 个跳过）
- **AND** series 表中每标的每天只多一条净值记录（不重复）

### AC-2 持有者崩溃自动接管

- **GIVEN** 实例 A 获得锁后进程崩溃
- **WHEN** locked_until 超过 TTL（30 分钟）
- **THEN** 下一轮定时触发时实例 B 成功获得锁并执行

### AC-3 拉完自动评估信号

- **GIVEN** 定时拉数成功
- **WHEN** 所有标的数据更新完成
- **THEN** 自动触发信号评估（无需用户手动点评估）
- **AND** 新信号写入 signals 表

### AC-4 过期数据自动刷新（S09-Lite 补充）

- **GIVEN** 用户打开小程序
- **WHEN** 任一标的最新净值距现在 > 6 小时
- **THEN** API 返回 `stale: true` + 前端显示"数据延迟"角标
- **AND** 总览页自动触发后台拉数（不阻塞页面渲染）

### AC-5 拉数日志可观测

- **GIVEN** 定时拉数执行
- **WHEN** 拉数完成
- **THEN** 日志记录：lock_holder / instruments_pulled / stale_skipped / duration / signal_evaluated
- **AND** 失败时 WARN 级 + 具体标的错误原因

## Out of Scope

- XXL-JOB 集成（规模化后再迁移）
- 分钟级行情（当前日级净值足够）
- 多数据源并行拉取优化
- 钉钉/飞书告警通知

## 实现要点（落地版）

1. **触发器零依赖**：不用 APScheduler——单个每日任务不值得多一个 pip 依赖；
   FastAPI lifespan 内 asyncio 循环（`next_run_at` 纯函数算下次触发点）。
   规模化（cron 管理/重试/告警）再迁 XXL-JOB，锁协议不变。
2. `src/invest/scheduler/` 新包：
   - `distributed_lock.py`：DistributedLock（starsite_lock 表语义，SQLite/MySQL
     双方言内联字面量 SQL；UPDATE 接管 + INSERT OR IGNORE 建行，恰一由
     UNIQUE(lock_name) 保证）
   - `pull_job.py`：pull_and_evaluate 共用核心 + run_pull_once（锁保护）+
     schedule_loop + status
3. 环境变量：`INVEST_SCHEDULE=1`（开关，docker-serve.sh 双容器默认开）/
   `INVEST_PULL_HOUR=20` / `INVEST_PULL_MINUTE=0` / `INVEST_PULL_LOCK_TTL_MIN=30` /
   `INVEST_AUTOPULL_ON_STALE`（AC-4 补拉门控：MySQL 部署默认开，本地默认关）
4. 观测：`GET /api/schedule/status`（开关/cron/下次触发/锁状态/最近执行）；
   overview 新增 `data_stale` 字段（前端角标数据源，S10 前端消费）
5. 顺带修复：pulljob 旧实现硬编码 LocalStore——MySQL 部署下手动拉数写进容器内
   SQLite 而读走 MySQL（数据永不上屏）；现统一走 default_store

## 已知取舍

- 错过触发点不回跑（进程重启跨越 20:00）：由 AC-4 过期补拉 + 次日定时兜底
- 手动拉数（pulljob）不参与分布式锁：用户显式动作，进程内单句柄已互斥；
  跨实例并发手动拉数数据面幂等（REPLACE INTO），可容忍
- 锁表时间戳为微秒 ISO 字符串（VARCHAR）：与 Java starsite-lock 组件表语义
  对齐但物理不互通（Java 侧 DATETIME）——如需互通需统一时间戳类型
