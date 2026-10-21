from invest.config import DEFAULT_ZONES
from invest.ledger.trades import Trade
from invest.strategy import evaluate_pension_contribution, zone_multiplier
from invest import config as cfg


def _portfolio(tmp_path):
    """最小配置：仅养老金标的，用于缴存规则测试。"""
    p = cfg.Portfolio(
        source="test",
        instruments=[cfg.Instrument(id="fund_a", type="open_end_fund", name="红利Y", account="pension")],
        accounts={"pension": cfg.Account(id="pension", name="养老金")},
        strategy=cfg.StrategyConfig(),
    )
    return p


def test_zone_multiplier():
    zones = list(DEFAULT_ZONES)
    assert zone_multiplier(0, zones)[0] == 2.0
    assert zone_multiplier(19.9, zones)[0] == 2.0
    assert zone_multiplier(20, zones)[0] == 1.5
    assert zone_multiplier(50, zones)[0] == 1.0
    assert zone_multiplier(84.9, zones)[0] == 0.5
    assert zone_multiplier(90, zones)[0] == 0.0


def test_pension_contribution_progress():
    p = _portfolio(None)
    ins = p.instruments[0]
    year = "2026"
    trades = [
        Trade(f"{year}-01-05", "fund_a", "contribute", 8000, 1.0),
        Trade(f"{year}-06-01", "fund_a", "contribute", 2000, 1.0),
        # 申购不占年度缴存额度（口径：缴存=contribute，申购=buy）
        Trade(f"{year}-07-01", "fund_a", "buy", 5000, 1.2),
    ]
    sig = evaluate_pension_contribution(ins, p, trades)
    assert "10,000/12,000" in sig.metric_value
    assert "还差 2,000" in sig.action


def test_pension_contribution_full():
    p = _portfolio(None)
    ins = p.instruments[0]
    trades = [Trade("2026-01-05", "fund_a", "contribute", 12000, 1.0)]
    sig = evaluate_pension_contribution(ins, p, trades)
    assert "已缴满" in sig.action


def test_pension_contribution_not_entered():
    p = _portfolio(None)
    sig = evaluate_pension_contribution(p.instruments[0], p, [])
    assert "未录入" in sig.metric_value
    assert "缴存" in sig.action
