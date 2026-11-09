"""S12 策略评估器：读最新数据 → 套策略规则 → 输出建议文案。

每个评估器签名统一：(store, instrument, params: dict) → dict | None
返回 {"action": str, "detail": str, "severity": "info|warn|action"}
"""
from __future__ import annotations


def eval_dca(store, ins, params: dict) -> dict:
    """定期定投：按频率提醒本期金额。"""
    amount = params.get("amount", 1000)
    freq = params.get("frequency", "每月")
    return {"action": f"本期定投 ¥{amount}", "detail": f"按{freq}频率执行，不择时不看盘", "severity": "info"}


def eval_smart_dca(store, ins, params: dict) -> dict:
    """估值定投：读基准指数 PE 分位 → 定投系数。"""
    bench_name = params.get("benchmark") or ins.benchmark_index or ""
    if not bench_name:
        return {"action": "请先配置跟踪指数", "detail": "估值定投需要知道跟踪哪个指数才能算 PE 分位", "severity": "warn"}
    base = float(params.get("base_amount", 1000))
    # 从估值表取 PE 分位（build_valuation_table 返回全量指数数据）
    from ..valuation import build_valuation_table

    table = build_valuation_table(store)
    entry = next((r for r in table if r.get("name") == bench_name or bench_name in (r.get("name") or "")), None)
    if not entry or not entry.get("ready"):
        return {"action": "暂无估值数据", "detail": f"「{bench_name}」的 PE 分位数据尚未拉取，请先拉数", "severity": "warn"}
    pct_5y = entry.get("pct_5y")
    if pct_5y is None:
        return {"action": "估值数据不完整", "detail": "PE 历史序列不足 5 年", "severity": "warn"}
    if pct_5y < 20:
        factor, zone = 2.0, "低估"
    elif pct_5y < 50:
        factor, zone = 1.5, "偏低"
    elif pct_5y < 70:
        factor, zone = 1.0, "中性"
    elif pct_5y < 85:
        factor, zone = 0.5, "偏高"
    else:
        return {"action": f"PE 分位 {pct_5y:.0f}%（高估）→ 暂停定投", "detail": f"「{bench_name}」估值处于历史高位，建议等待回归", "severity": "action"}
    amount = int(base * factor)
    return {"action": f"PE 分位 {pct_5y:.0f}%（{zone}）→ 本期 ¥{amount}", "detail": f"基准 ¥{base} × 系数 {factor}（{bench_name} 5年分位）", "severity": "info"}


def eval_rebalance(store, ins, params: dict) -> dict:
    """目标再平衡：当前占比 vs 目标 ± 容忍带。"""
    # 简化版：只报当前占比 vs 目标（实际计算需组合层数据）
    target = float(params.get("target_pct", 30))
    tol = float(params.get("tolerance", 10))
    return {"action": f"目标占比 {target}%（容忍 ±{tol}pct）", "detail": "到总览页查看当前持仓占比，偏离时在此提醒", "severity": "info"}


def eval_hold_maturity(store, ins, params: dict) -> dict:
    """持有到期：展示当前价格 vs 面值。"""
    from ..config import series_kind

    series_key = ins.code or ins.id
    latest = store.latest(series_key, series_kind(ins.type))
    if not latest:
        return {"action": "暂无价格数据", "detail": "请先拉数", "severity": "warn"}
    price = latest[1]
    face = float(params.get("face_value", 100))
    if price < face:
        gain = (face - price) / price * 100
        return {"action": f"当前 ¥{price:.2f} < 面值 ¥{face:.0f}", "detail": f"持有到期资本利得 +{gain:.1f}%（不含票息）", "severity": "info"}
    elif price > face:
        loss = (price - face) / price * 100
        return {"action": f"当前 ¥{price:.2f} > 面值 ¥{face:.0f}", "detail": f"溢价 {loss:.1f}%，持有到期有价格回归损失（票息可对冲）", "severity": "warn"}
    return {"action": f"当前价格 = 面值", "detail": "持有到期收益 ≈ 票面利率", "severity": "info"}


def eval_ladder(store, ins, params: dict) -> dict:
    """阶梯配置：提醒到期滚动。"""
    rungs = int(params.get("rungs", 3))
    return {"action": f"阶梯 {rungs} 级配置", "detail": f"分 {rungs} 期买入不同期限，每年有 1/{rungs} 到期可再配置", "severity": "info"}


def eval_dividend(store, ins, params: dict) -> dict:
    """股息收息：当前股息率 vs 最低要求。"""
    series_key = ins.code or ins.id
    latest = store.latest(series_key, series_kind(ins.type))
    if not latest:
        return {"action": "暂无价格数据", "detail": "请先拉数", "severity": "warn"}
    min_yield = float(params.get("min_yield", 4.0))
    # 股息率需要额外数据，此处用简化判断
    return {"action": f"股息收息策略（要求 ≥{min_yield}%）", "detail": "当前股息率请查看标的详情页的基准估值", "severity": "info"}


def eval_value_revert(store, ins, params: dict) -> dict:
    """价值回归：PE 分位 < 低估线 → 买入建议。"""
    bench_name = ins.benchmark_index or ""
    if not bench_name:
        return {"action": "请先配置跟踪指数", "detail": "价值回归需要 PE 分位数据", "severity": "warn"}
    from ..valuation import build_valuation_table

    table = build_valuation_table(store)
    entry = next((r for r in table if r.get("name") == bench_name), None)
    if not entry or entry.get("pct_5y") is None:
        return {"action": "暂无估值数据", "detail": "请先拉数", "severity": "warn"}
    pct = entry["pct_5y"]
    low = float(params.get("low_pct", 20))
    high = float(params.get("high_pct", 80))
    if pct < low:
        return {"action": f"PE 分位 {pct:.0f}% < {low}%（低估区）→ 建议分批买入", "detail": f"「{bench_name}」处于历史低位，均值回归概率较高", "severity": "action"}
    elif pct > high:
        return {"action": f"PE 分位 {pct:.0f}% > {high}%（高估区）→ 建议分批止盈", "detail": f"「{bench_name}」处于历史高位，可考虑部分获利了结", "severity": "action"}
    return {"action": f"PE 分位 {pct:.0f}%（中性区）", "detail": f"持有不动，等待分位进入 <{low}% 或 >{high}% 区间", "severity": "info"}


def eval_lock_rate(store, ins, params: dict) -> dict:
    """锁定收益：收益率 vs 阈值。"""
    threshold = float(params.get("threshold", 3.0))
    # 尝试取 10Y 国债收益率做参考
    cn10y = store.latest("CN10Y", "bond_yield")
    if cn10y:
        rate = cn10y[1]
        if rate >= threshold:
            return {"action": f"10Y 国债 {rate:.2f}% ≥ 阈值 {threshold}%", "detail": "利率处于相对高位，可考虑锁定长期限", "severity": "info"}
        else:
            return {"action": f"10Y 国债 {rate:.2f}% < 阈值 {threshold}%", "detail": "利率偏低，可等待回升再配置", "severity": "info"}
    return {"action": "暂无利率数据", "detail": "请先拉数", "severity": "warn"}


EVALUATORS = {
    "eval_dca": eval_dca,
    "eval_smart_dca": eval_smart_dca,
    "eval_rebalance": eval_rebalance,
    "eval_hold_maturity": eval_hold_maturity,
    "eval_ladder": eval_ladder,
    "eval_dividend": eval_dividend,
    "eval_value_revert": eval_value_revert,
    "eval_lock_rate": eval_lock_rate,
}
