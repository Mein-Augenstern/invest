# invest SDD（Spec-Driven Development）框架

> 本目录是 invest 项目的**唯一需求真相源**。所有功能改动必须先写 Spec、评审通过后实现、
> 实现后对照 Spec 验收——杜绝"先写代码再补文档"。

## 开发流程（SDD 三步法）

```
① 写 Spec → ② 实现 → ③ 验收
   ↓              ↓           ↓
docs/sdd/       src/         tests/
SXX-*.md        代码变更      AC 全过才关闭
```

### ① 写 Spec（30 分钟）
每个 Spec 必须包含：
- **Problem**：用户视角的问题（不是技术视角）
- **User Story**：作为X，我想要Y，以便Z
- **Acceptance Criteria**（AC）： GIVEN-WHEN-THEN 格式，可机器验证
- **Out of Scope**：明确不做什么（防蔓延）
- **Priority**：P0(必须) P1(应该) P2(可以)

### ② 实现（遵循 CLAUDE.md 约束）
- 代码必须满足 Spec 的每一条 AC
- 新增公开方法必须有 javadoc/docstring
- SQL 必须参数化（? 占位符）
- 并发写入必须加锁

### ③ 验收（自动+手动）
- 自动：pytest 单测覆盖每条 AC
- 手动：小程序真机验证 User Story 是否达成
- Spec 关闭时在文档末尾追加 `## 验收记录` 节

## Spec 索引

| Spec | 标题 | 状态 | 优先级 |
|---|---|---|---|
| [S01](../prd/spec-S01-real-portfolio.md) | 真实组合配置 | 🔄 进行中 | P0 |
| [S02](../prd/spec-S02-strategy-engine.md) | 策略引擎 v1 | ✅ 完成 | P1 |
| [S03](S03-error-recovery.md) | 全局错误处理与自愈 | ✅ 已实现（pytest 覆盖，验收记录待补） | P0 |
| [S04](S04-data-integrity.md) | 数据完整性与并发安全 | ✅ 已实现（pytest 覆盖，验收记录待补） | P0 |
| [S05](S05-external-resilience.md) | 外部 API 韧性（超时/重试/熔断） | ✅ 已实现（pytest 覆盖，验收记录待补） | P1 |
| [S06](S06-ux-patterns.md) | 页面 UX 模式规范（加载/空/错/重试） | ✅ 已实现（前端组件，验收记录待补） | P1 |
| [S07](S07-navigation.md) | 导航与信息架构 | ✅ 已实现（验收记录待补） | P2 |
| [S08](S08-onboarding.md) | 首次使用引导 | ✅ 已实现（前端组件，验收记录待补） | P2 |
| [S09](S09-distributed-schedule.md) | 分布式定时拉数 | ✅ 生产验收（2026-11-06） | P0 |
| [S10](S10-pc-web.md) | PC Web 端（invest-web） | 🔄 进行中 | P1 |

## 稳定性优先原则

> **"不要求功能有多少，而要求功能的稳定"**——每个已上线功能先做到：
> 1. 任何输入不崩溃（错误处理）
> 2. 任何操作不丢数据（完整性）
> 3. 外部依赖不阻塞（韧性）
> 4. 加载慢时有反馈（UX 模式）
> 5. 出错时有重试入口（自愈）

## 修改规则

- 修改已有功能 → 先修改对应 Spec → 再修改代码
- 新增功能 → 先新建 SXX Spec → 评审 → 再实现
- Bug 修复 → 在对应 Spec 的 AC 中补充回归用例 → 再修代码
- Spec 与代码不一致 → 以 Spec 为准修代码（Spec 是合同）
