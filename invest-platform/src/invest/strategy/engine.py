"""策略规则引擎（S02-A）：可配置规则 → 阈值比较 → 加权综合信号。

与 strategy/__init__.py（规则书逐条硬编码：PE分位定投/缴存进度/再平衡）的分工：
那边按 docs/02-strategy-rules.md 的固定条款实现；这边是数据驱动的通用引擎——
规则来自 YAML（config/strategy.local.yaml，不入 git）或 DEFAULT_RULES，
指标由调用方（metrics 模块）算好以 dict 传入，引擎只做"阈值比较 + 加权综合"。

刻意保持纯计算、零 IO（除 load_rules 读配置），便于单测与回测复用。
信号 = 规则 + 数据，仅作为纪律工具；执行与否由用户确认（红线：不自动下单）。

口径约定（与 metrics 模块对齐）：
- pe_percentile_5y 等 *_percentile 指标：0~100（百分数数值，非小数）
- max_drawdown_1y 等回撤指标：正小数表示跌幅（0.15 = 跌 15%），命中规则由调用方保证口径
- between 为双端闭区间 [lo, hi]；lt/gt 严格不等，lte/gte 含等号
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

#: 支持的比较操作符 → 人话符号（description 用）
_OP_SYMBOLS: dict[str, str] = {"lt": "<", "gt": ">", "lte": "<=", "gte": ">=", "between": "∈"}
_SIGNALS: frozenset[str] = frozenset({"buy", "hold", "sell", "rebalance", "ignore"})


@dataclass
class Rule:
    """单条规则：指标 + 操作符 + 阈值 → 信号与权重。

    value：lt/gt/lte/gte 为 float；between 为 (lo, hi) 元组（闭区间）。
    """

    id: str
    name: str
    metric: str  # 指标名，如 "pe_percentile_5y" | "max_drawdown_1y" | "close_vs_sma200"
    operator: str  # lt | gt | lte | gte | between
    value: float | tuple[float, float]
    signal: str  # buy | hold | sell | rebalance | ignore
    weight: float  # 0.0 ~ 1.0，多规则综合时的贡献权重
    note: str = ""  # 规则说明（进 description/人话总结）

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("规则 id 不能为空")
        if self.operator not in _OP_SYMBOLS:
            raise ValueError(f"规则 {self.id}：未知操作符 {self.operator!r}（可选：{'/'.join(_OP_SYMBOLS)}）")
        if self.signal not in _SIGNALS:
            raise ValueError(f"规则 {self.id}：未知信号 {self.signal!r}（可选：{'/'.join(sorted(_SIGNALS))}）")
        if not 0.0 <= float(self.weight) <= 1.0:
            raise ValueError(f"规则 {self.id}：weight 需在 0~1，实际 {self.weight}")
        self.weight = float(self.weight)
        if self.operator == "between":
            pair = tuple(self.value) if isinstance(self.value, (list, tuple)) else (self.value,)
            if len(pair) != 2:
                raise ValueError(f"规则 {self.id}：between 的 value 需为 [lo, hi] 两元素，实际 {self.value!r}")
            lo, hi = float(pair[0]), float(pair[1])
            if lo > hi:
                raise ValueError(f"规则 {self.id}：between 区间下界 {lo:g} > 上界 {hi:g}")
            self.value = (lo, hi)
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(f"规则 {self.id}：value 需为数值，实际 {self.value!r}")
            self.value = float(self.value)


@dataclass
class RuleResult:
    """单条规则的评估结果。"""

    rule: Rule
    triggered: bool  # 是否命中（指标缺失/无效视为未命中）
    metric_value: float | None  # 指标实际值；缺失/NaN 时为 None
    description: str  # 人话描述，如 "PE低估：pe_percentile_5y=15.2 < 20，命中（PE 5年分位<20%，历史低估区间）"


@dataclass
class CompositeSignal:
    """单个标的的综合信号：全部规则评估后加权综合。"""

    instrument_id: str
    final_signal: str  # buy/hold/sell/rebalance/ignore；无命中时为 hold
    confidence: float  # 0~1：命中规则权重之和（封顶 1.0）
    results: list[RuleResult]  # 各规则命中明细
    summary: str  # 人话总结（含命中明细）


#: 默认规则集（规则书提取；config/strategy.local.yaml 缺省时的兜底）
DEFAULT_RULES: list[Rule] = [
    Rule(id="pe-low", name="PE低估", metric="pe_percentile_5y", operator="lt", value=20,
         signal="buy", weight=0.4, note="PE 5年分位<20%，历史低估区间"),
    Rule(id="pe-high", name="PE高估", metric="pe_percentile_5y", operator="gt", value=80,
         signal="sell", weight=0.4, note="PE 5年分位>80%，历史高估区间"),
    Rule(id="drawdown", name="回撤保护", metric="max_drawdown_1y", operator="gt", value=0.15,
         signal="rebalance", weight=0.3, note="近一年回撤>15%，触发再平衡检查"),
]


def _fmt(v: float) -> str:
    """数值转简短文本（15.0 → '15'，0.1500001 → '0.15'）。"""
    return f"{v:g}"


def _compare(value: float, rule: Rule) -> bool:
    """阈值比较；between 为双端闭区间。"""
    if rule.operator == "lt":
        return value < rule.value
    if rule.operator == "gt":
        return value > rule.value
    if rule.operator == "lte":
        return value <= rule.value
    if rule.operator == "gte":
        return value >= rule.value
    lo, hi = rule.value
    return lo <= value <= hi


def _describe(rule: Rule, value: float, hit: bool) -> str:
    """拼单条规则的人话描述。"""
    if rule.operator == "between":
        lo, hi = rule.value
        cond = f"{rule.metric}={_fmt(value)} {_OP_SYMBOLS[rule.operator]} [{_fmt(lo)}, {_fmt(hi)}]"
    else:
        cond = f"{rule.metric}={_fmt(value)} {_OP_SYMBOLS[rule.operator]} {_fmt(rule.value)}"
    verdict = "命中" if hit else "未命中"
    note = f"（{rule.note}）" if rule.note else ""
    return f"{rule.name}：{cond}，{verdict}{note}"


class StrategyEngine:
    """规则评估引擎：rules 由 YAML 或 DEFAULT_RULES 构造，evaluate 纯计算。"""

    def __init__(self, rules: list[Rule]):
        # 复制入参列表：外部改动（如 clear）不影响引擎
        self.rules = list(rules)

    def evaluate(self, instrument_id: str, metrics: dict[str, float]) -> CompositeSignal:
        """对单个标的评估所有规则 → 加权综合信号。

        metrics：{"pe_percentile_5y": 15.2, ...}；值可为 None/NaN（视为指标缺失，
        对应规则不命中，metric_value 记 None——与 metrics 模块的 Optional 返回对齐）。

        综合：confidence = 命中规则权重之和（封顶 1.0）；
        final_signal = 命中规则中 weight 最高者的 signal（并列取先声明者）；
        全未命中/无规则 → hold（纪律默认：不折腾）。
        """
        results = [self._eval_rule(rule, metrics) for rule in self.rules]
        triggered = [r for r in results if r.triggered]
        if triggered:
            best = max(triggered, key=lambda r: r.rule.weight)  # 并列时 max 取先出现者
            confidence = min(1.0, sum(r.rule.weight for r in triggered))
            detail = "；".join(r.description for r in triggered)
            summary = (f"{instrument_id}：命中 {len(triggered)}/{len(results)} 条规则，"
                       f"综合信号 {best.rule.signal}（置信度 {confidence:.2f}）。{detail}")
            return CompositeSignal(instrument_id, best.rule.signal, confidence, results, summary)
        if self.rules:
            summary = f"{instrument_id}：{len(results)} 条规则均未命中，维持 hold（不折腾）。"
        else:
            summary = f"{instrument_id}：无已配置规则，维持 hold。"
        return CompositeSignal(instrument_id, "hold", 0.0, results, summary)

    def _eval_rule(self, rule: Rule, metrics: dict[str, float]) -> RuleResult:
        """评一条规则：指标缺失/NaN → 未命中且 metric_value=None。"""
        raw = metrics.get(rule.metric)
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            return RuleResult(rule, False, None, f"{rule.name}：缺少指标 {rule.metric}，跳过评估")
        value = float(raw)
        hit = _compare(value, rule)
        return RuleResult(rule, hit, value, _describe(rule, value, hit))


def load_rules(yaml_path: Path) -> list[Rule]:
    """从 strategy.local.yaml 加载规则列表。

    YAML 结构（对齐 config/portfolio.example.yaml 风格）::

        rules:
          - id: pe-low
            name: PE低估
            metric: pe_percentile_5y
            operator: lt          # lt|gt|lte|gte|between
            value: 20             # between 时为 [lo, hi] 两元素列表
            signal: buy           # buy|hold|sell|rebalance|ignore
            weight: 0.4
            note: "..."           # 可选
            enabled: true         # 可选，缺省 true；false 跳过该规则

    name/note/weight 缺省分别为 id/空串/1.0；非法配置抛 ValueError（带文件名与规则 id）。
    """
    path = Path(yaml_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML 顶层应为 mapping（rules: ...），实际是 {type(data).__name__}")
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"{path}: rules 应为列表，实际是 {type(raw_rules).__name__}")
    rules: list[Rule] = []
    for i, item in enumerate(raw_rules):
        rid = item.get("id", f"<rules[{i}]>") if isinstance(item, dict) else f"<rules[{i}]>"
        if not isinstance(item, dict):
            raise ValueError(f"{path}: 规则 {rid} 应为 mapping，实际是 {type(item).__name__}")
        if item.get("enabled", True) is False:
            continue
        try:
            rules.append(Rule(
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                metric=str(item["metric"]),
                operator=str(item["operator"]),
                value=item["value"],
                signal=str(item["signal"]),
                weight=item.get("weight", 1.0),
                note=str(item.get("note", "") or ""),
            ))
        except KeyError as e:
            raise ValueError(f"{path}: 规则 {rid} 缺少必填字段 {e}（id/metric/operator/value/signal）") from None
    return rules
