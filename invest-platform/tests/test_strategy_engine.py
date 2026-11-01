"""strategy.engine 单测：单规则命中、加权综合、YAML 加载、边界值、空规则。"""
import pytest

from invest.strategy.engine import (
    DEFAULT_RULES,
    CompositeSignal,
    Rule,
    StrategyEngine,
    load_rules,
)

# 与 DEFAULT_RULES 同构的测试规则（避免直接改公共常量）
PE_LOW = Rule(id="pe-low", name="PE低估", metric="pe_percentile_5y", operator="lt",
              value=20, signal="buy", weight=0.4, note="PE 5年分位<20%，历史低估区间")
DRAWDOWN = Rule(id="drawdown", name="回撤保护", metric="max_drawdown_1y", operator="gt",
                value=0.15, signal="rebalance", weight=0.3, note="近一年回撤>15%，触发再平衡检查")


# ---- 单规则命中 / 不命中 ----


def test_single_rule_hit():
    sig = StrategyEngine([PE_LOW]).evaluate("consumer50_etf", {"pe_percentile_5y": 15.2})
    assert isinstance(sig, CompositeSignal)
    assert sig.instrument_id == "consumer50_etf"
    assert sig.final_signal == "buy"
    assert sig.confidence == pytest.approx(0.4)
    assert len(sig.results) == 1
    r = sig.results[0]
    assert r.triggered is True
    assert r.metric_value == pytest.approx(15.2)
    assert "命中" in r.description
    assert "pe_percentile_5y" in r.description
    assert "PE低估" in sig.summary


def test_single_rule_miss():
    sig = StrategyEngine([PE_LOW]).evaluate("consumer50_etf", {"pe_percentile_5y": 25})
    assert sig.final_signal == "hold"  # 未命中 → 纪律默认 hold
    assert sig.confidence == 0.0
    assert sig.results[0].triggered is False
    assert "未命中" in sig.results[0].description


def test_metric_missing_treated_as_not_triggered():
    """指标缺失（不在 dict / None / NaN）→ 未命中且 metric_value=None。"""
    eng = StrategyEngine([PE_LOW])
    for metrics in ({}, {"pe_percentile_5y": None}, {"pe_percentile_5y": float("nan")}):
        sig = eng.evaluate("x", metrics)
        assert sig.final_signal == "hold"
        r = sig.results[0]
        assert r.triggered is False
        assert r.metric_value is None
        assert "缺少指标" in r.description


# ---- 边界值：恰好等于阈值 ----


def test_boundary_lt_exclusive():
    """lt 恰好等于阈值 → 不命中（严格小于）。"""
    assert StrategyEngine([PE_LOW]).evaluate("x", {"pe_percentile_5y": 20}).results[0].triggered is False
    assert StrategyEngine([PE_LOW]).evaluate("x", {"pe_percentile_5y": 19.999}).results[0].triggered is True


def test_boundary_gt_exclusive():
    """gt 恰好等于阈值 → 不命中；略超 → 命中。"""
    eng = StrategyEngine([DRAWDOWN])
    assert eng.evaluate("x", {"max_drawdown_1y": 0.15}).results[0].triggered is False
    assert eng.evaluate("x", {"max_drawdown_1y": 0.1500001}).results[0].triggered is True


def test_boundary_lte_gte_inclusive():
    """lte/gte 恰好等于阈值 → 命中（含等号）。"""
    lte = Rule(id="u", name="上限", metric="m", operator="lte", value=1.5, signal="sell", weight=0.1)
    gte = Rule(id="d", name="下限", metric="m", operator="gte", value=1.5, signal="hold", weight=0.1)
    sig = StrategyEngine([lte, gte]).evaluate("x", {"m": 1.5})
    assert {r.rule.id for r in sig.results if r.triggered} == {"u", "d"}


def test_boundary_between_closed_interval():
    """between 为双端闭区间：端点命中，越界不命中。"""
    band = Rule(id="band", name="波动带", metric="vol_1y", operator="between",
                value=(0.15, 0.25), signal="hold", weight=0.2)
    eng = StrategyEngine([band])
    for v in (0.15, 0.2, 0.25):
        assert eng.evaluate("x", {"vol_1y": v}).results[0].triggered is True
    for v in (0.1499, 0.2501):
        assert eng.evaluate("x", {"vol_1y": v}).results[0].triggered is False


# ---- 多规则加权综合 ----


def test_weighted_composite_signal():
    """多规则同时命中：final_signal 取命中规则中权重最高者，confidence=权重和。"""
    sig = StrategyEngine([PE_LOW, DRAWDOWN]).evaluate(
        "consumer50_etf", {"pe_percentile_5y": 15.2, "max_drawdown_1y": 0.18}
    )
    assert sig.final_signal == "buy"  # 0.4 > 0.3
    assert sig.confidence == pytest.approx(0.4 + 0.3)
    assert all(r.triggered for r in sig.results)
    assert "2/2" in sig.summary
    assert "PE低估" in sig.summary and "回撤保护" in sig.summary


def test_weight_tie_breaks_by_declaration_order():
    """权重并列时取先声明的规则信号（max 语义，确定性输出）。"""
    rules = [
        Rule(id="a", name="A", metric="m", operator="gt", value=0, signal="buy", weight=0.5),
        Rule(id="b", name="B", metric="m", operator="gt", value=0, signal="sell", weight=0.5),
    ]
    assert StrategyEngine(rules).evaluate("x", {"m": 1}).final_signal == "buy"


def test_confidence_clamped_to_one():
    """命中权重之和超 1 时封顶 1.0。"""
    rules = [
        Rule(id="a", name="A", metric="m", operator="gt", value=0, signal="buy", weight=0.8),
        Rule(id="b", name="B", metric="m", operator="gt", value=0, signal="sell", weight=0.8),
    ]
    assert StrategyEngine(rules).evaluate("x", {"m": 1}).confidence == 1.0


def test_higher_weight_sell_overrides_lower_weight_buy():
    rules = [
        Rule(id="lo", name="低估", metric="pe_percentile_5y", operator="lt", value=20, signal="buy", weight=0.2),
        Rule(id="dd", name="回撤", metric="max_drawdown_1y", operator="gt", value=0.1,
             signal="sell", weight=0.6),
    ]
    sig = StrategyEngine(rules).evaluate("x", {"pe_percentile_5y": 10, "max_drawdown_1y": 0.2})
    assert sig.final_signal == "sell"
    assert sig.confidence == pytest.approx(0.8)


# ---- 空规则列表 / 全未命中 / 默认规则集 ----


def test_empty_rules_list():
    sig = StrategyEngine([]).evaluate("x", {"pe_percentile_5y": 5})
    assert sig.final_signal == "hold"
    assert sig.confidence == 0.0
    assert sig.results == []
    assert "无已配置规则" in sig.summary


def test_no_rule_triggered():
    sig = StrategyEngine(DEFAULT_RULES).evaluate(
        "x", {"pe_percentile_5y": 50, "max_drawdown_1y": 0.05}
    )
    assert sig.final_signal == "hold"
    assert sig.confidence == 0.0
    assert "均未命中" in sig.summary


def test_default_rules_low_valuation_buy():
    sig = StrategyEngine(DEFAULT_RULES).evaluate(
        "consumer50_etf", {"pe_percentile_5y": 15.2, "max_drawdown_1y": 0.08}
    )
    assert sig.final_signal == "buy"
    assert sig.confidence == pytest.approx(0.4)


def test_engine_isolates_rule_list():
    """外部改动 rules 列表不影响引擎（构造时复制）。"""
    rules = [PE_LOW]
    eng = StrategyEngine(rules)
    rules.clear()
    assert len(eng.rules) == 1
    assert eng.evaluate("x", {"pe_percentile_5y": 10}).final_signal == "buy"


# ---- 规则校验 ----


def test_rule_validation_errors():
    base = dict(id="r", name="r", metric="m", operator="lt", value=1, signal="buy", weight=0.5)

    def build(**override):
        kwargs = {**base, **override}
        return Rule(**kwargs)

    with pytest.raises(ValueError, match="操作符"):
        build(operator="eq")
    with pytest.raises(ValueError, match="信号"):
        build(signal="panic")
    with pytest.raises(ValueError, match="weight"):
        build(weight=1.5)
    with pytest.raises(ValueError, match="between"):
        build(operator="between", value=5)
    with pytest.raises(ValueError, match="between"):
        build(operator="between", value=[0.5, 0.2])  # 下界 > 上界
    with pytest.raises(ValueError, match="id"):
        Rule(id="", name="r", metric="m", operator="lt", value=1, signal="buy", weight=0.5)


# ---- YAML 加载（临时文件） ----

YAML_CONTENT = """\
# 测试用规则配置（结构与 config/strategy.local.yaml 一致）
rules:
  - id: pe-low
    name: PE低估
    metric: pe_percentile_5y
    operator: lt
    value: 20
    signal: buy
    weight: 0.4
    note: "PE 5年分位<20%，历史低估区间"

  - id: vol-band
    metric: vol_1y
    operator: between
    value: [0.15, 0.25]     # between → [lo, hi] 列表
    signal: hold
    weight: 0.2

  - id: disabled-one
    name: 已停用
    metric: pe_percentile_5y
    operator: gt
    value: 60
    signal: sell
    weight: 0.9
    enabled: false
"""


def test_load_rules_from_yaml(tmp_path):
    p = tmp_path / "strategy.local.yaml"
    p.write_text(YAML_CONTENT, encoding="utf-8")
    rules = load_rules(p)
    assert [r.id for r in rules] == ["pe-low", "vol-band"]  # enabled:false 跳过
    pe, band = rules
    assert pe.note == "PE 5年分位<20%，历史低估区间"
    assert pe.value == 20.0 and isinstance(pe.value, float)
    assert band.value == (0.15, 0.25) and isinstance(band.value, tuple)  # 列表 → 元组
    # name 缺省回落到 id
    assert band.name == "vol-band"
    # 加载结果可直接喂引擎
    sig = StrategyEngine(rules).evaluate("x", {"pe_percentile_5y": 10, "vol_1y": 0.2})
    assert sig.final_signal == "buy"


def test_load_rules_defaults_and_empty(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(
        "rules:\n  - {id: only, metric: m, operator: gt, value: 1, signal: sell}\n",
        encoding="utf-8",
    )
    r = load_rules(p)[0]
    assert r.name == "only"
    assert r.weight == 1.0
    assert r.note == ""
    # 空 rules / 空文件 → 空列表
    p2 = tmp_path / "empty.yaml"
    p2.write_text("rules: []\n", encoding="utf-8")
    assert load_rules(p2) == []
    p3 = tmp_path / "blank.yaml"
    p3.write_text("", encoding="utf-8")
    assert load_rules(p3) == []


def test_load_rules_config_errors(tmp_path):
    # 顶层不是 mapping
    p1 = tmp_path / "bad1.yaml"
    p1.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="顶层"):
        load_rules(p1)
    # rules 不是列表
    p2 = tmp_path / "bad2.yaml"
    p2.write_text("rules: {a: 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="rules 应为列表"):
        load_rules(p2)
    # 缺必填字段（value/signal）
    p3 = tmp_path / "bad3.yaml"
    p3.write_text("rules:\n  - {id: x, metric: m, operator: lt}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少必填字段"):
        load_rules(p3)
    # 非法操作符（Rule 校验透传，报错带规则 id）
    p4 = tmp_path / "bad4.yaml"
    p4.write_text("rules:\n  - {id: x, metric: m, operator: eq, value: 1, signal: buy}\n",
                  encoding="utf-8")
    with pytest.raises(ValueError, match="规则 x"):
        load_rules(p4)
