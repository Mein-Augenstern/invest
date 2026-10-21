# invest 文档索引

> 按三类组织：**PRD（产品）**、**业务**、**技术（前端/后端）**。
> 文件已语义化命名，阅读顺序即推荐入门路径。

## PRD（产品）

| 文档 | 内容 |
|------|------|
| [prd/product.md](prd/product.md) | **产品需求文档**：定位、用户故事、功能清单、非功能需求、边界 |
| [prd/charter.md](prd/charter.md) | 项目章程（v2.0）：使命、价值层次、红线边界、干系人 |
| [prd/roadmap.md](prd/roadmap.md) | 路线图与里程碑 |

## 业务

| 文档 | 内容 |
|------|------|
| [business/overview.md](business/overview.md) | **业务总览**：五品类体系、记账/统计/信号/复盘/提醒业务流 |
| [business/strategy-rules.md](business/strategy-rules.md) | 策略规则书：估值分位定投、缴存、再平衡（改参数必留痕） |
| [business/data-sources.md](business/data-sources.md) | 数据源与口径登记 |

## 技术

| 文档 | 内容 |
|------|------|
| [tech/architecture.md](tech/architecture.md) | **全仓架构总览**：架构图、模块清单、调用链、端口/env、部署形态、踩坑沉淀 |
| [tech/frontend/](tech/frontend/) | 前端：[miniapp-engineering.md](tech/frontend/miniapp-engineering.md) 工程指南（API 层/构建链/UI 规范/E2E） |
| [tech/backend/](tech/backend/) | 后端：[api-contract.md](tech/backend/api-contract.md) API 契约 · [web-architecture.md](tech/backend/web-architecture.md) Web 架构 · [backtest.md](tech/backend/backtest.md) 回测引擎 |

## 维护约定

- 新文档落对应子目录，文件名语义化（不用全局编号）
- 代码内引用文档路径一律从仓根写起（如 `docs/business/strategy-rules.md`）
- 架构级改动（新模块/新链路/端口变化）必须同步 `tech/architecture.md`
