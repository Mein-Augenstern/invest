"""S12 投资策略库：品类匹配的策略模板 + 绑定 + 评估。

设计原则：
- 模板是静态注册的（代码即配置），不建表存模板定义
- 绑定存 strategy_bindings 表（member_id 隔离）
- 评估 = 读最新估值/行情 → 套策略规则 → 输出建议文案
- 回测复用现有 backtest 引擎，传入策略参数
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyTemplate:
    id: str
    name: str
    desc: str
    # 适用的标的品类（INSTRUMENT_TYPES 的子集）
    types: list[str]
    # 参数定义（前端渲染表单用）
    params: list[dict] = field(default_factory=list)
    # 信号评估函数（store, instrument, params → 信号文案）
    evaluator: str = ""  # 函数名，路由层 dispatch


TEMPLATES: list[StrategyTemplate] = [
    # ---- 基金 / ETF ----
    StrategyTemplate(
        id="dca",
        name="定期定投",
        desc="每月固定金额买入，不择时、不看盘，时间换空间。适合波动大的指数基金。",
        types=["open_end_fund", "etf"],
        params=[
            {"key": "amount", "label": "每期金额", "type": "number", "default": 1000, "unit": "元"},
            {"key": "frequency", "label": "频率", "type": "select", "options": ["每周", "每两周", "每月"], "default": "每月"},
        ],
        evaluator="eval_dca",
    ),
    StrategyTemplate(
        id="smart_dca",
        name="估值定投",
        desc="PE 分位越低买越多：低估 ×2.0 / 低估偏多 ×1.5 / 中性 ×1.0 / 偏高 ×0.5 / 高估停止。适合指数基金。",
        types=["open_end_fund", "etf"],
        params=[
            {"key": "base_amount", "label": "基准金额", "type": "number", "default": 1000, "unit": "元"},
            {"key": "benchmark", "label": "估值基准", "type": "text", "default": "", "placeholder": "跟踪指数名（如 中证红利）"},
        ],
        evaluator="eval_smart_dca",
    ),
    StrategyTemplate(
        id="rebalance",
        name="目标再平衡",
        desc="设定目标配置比例，偏离 ±10pct 时提醒调仓。适合多标的长持。",
        types=["open_end_fund", "etf", "bond", "wealth"],
        params=[
            {"key": "target_pct", "label": "目标占比", "type": "number", "default": 30, "unit": "%"},
            {"key": "tolerance", "label": "容忍带", "type": "number", "default": 10, "unit": "pct"},
        ],
        evaluator="eval_rebalance",
    ),
    # ---- 债券 ----
    StrategyTemplate(
        id="hold_maturity",
        name="持有到期",
        desc="买入后持有至到期日，吃票息+面值回归。国债的零风险策略。",
        types=["bond"],
        params=[
            {"key": "face_value", "label": "面值", "type": "number", "default": 100, "unit": "元"},
        ],
        evaluator="eval_hold_maturity",
    ),
    StrategyTemplate(
        id="ladder",
        name="阶梯配置",
        desc="分散买入不同期限的债券，每年都有到期资金可再配置。流动性+收益兼顾。",
        types=["bond"],
        params=[
            {"key": "rungs", "label": "阶梯数", "type": "number", "default": 3, "unit": "级"},
        ],
        evaluator="eval_ladder",
    ),
    # ---- 股票 ----
    StrategyTemplate(
        id="dividend_income",
        name="股息收息",
        desc="买入高股息率股票长期持有，吃分红。股息率 > 2× 10Y 国债收益率时为佳。",
        types=["stock"],
        params=[
            {"key": "min_yield", "label": "最低股息率", "type": "number", "default": 4.0, "unit": "%"},
        ],
        evaluator="eval_dividend",
    ),
    StrategyTemplate(
        id="value_revert",
        name="价值回归",
        desc="PE 历史分位 < 20% 时分批买入，> 80% 时分批卖出。均值回归逻辑。",
        types=["stock", "etf", "open_end_fund"],
        params=[
            {"key": "low_pct", "label": "低估分位", "type": "number", "default": 20, "unit": "%"},
            {"key": "high_pct", "label": "高估分位", "type": "number", "default": 80, "unit": "%"},
        ],
        evaluator="eval_value_revert",
    ),
    # ---- 理财 ----
    StrategyTemplate(
        id="lock_rate",
        name="锁定收益",
        desc="收益率高于近 1 年均值时买入长期限，锁定利率。利率下行周期的保护策略。",
        types=["wealth"],
        params=[
            {"key": "threshold", "label": "买入阈值", "type": "number", "default": 3.0, "unit": "%"},
        ],
        evaluator="eval_lock_rate",
    ),
]


def templates_for_type(itype: str) -> list[dict]:
    """返回适用于某品类的策略模板（前端渲染用）。"""
    return [
        {
            "id": t.id, "name": t.name, "desc": t.desc,
            "params": t.params, "types": t.types,
        }
        for t in TEMPLATES if itype in t.types
    ]


def get_template(tid: str) -> StrategyTemplate | None:
    return next((t for t in TEMPLATES if t.id == tid), None)
