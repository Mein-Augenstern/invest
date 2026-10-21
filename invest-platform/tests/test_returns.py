from invest.ledger.returns import xirr


def test_xirr_single_year_gain():
    # 投入10000，365天后市值11000 → 10%
    r = xirr([("2025-01-01", -10000.0)], "2026-01-01", 11000.0)
    assert abs(r - 0.10) < 1e-6


def test_xirr_single_year_loss():
    r = xirr([("2025-01-01", -10000.0)], "2026-01-01", 9000.0)
    assert abs(r + 0.10) < 1e-6


def test_xirr_two_flows():
    # -1000 @t0, -1000 @1y, 市值2300 @2y（闰年致期限略偏，期望≈9.67%）
    r = xirr(
        [("2024-01-01", -1000.0), ("2025-01-01", -1000.0)],
        "2026-01-01",
        2300.0,
    )
    assert abs(r - 0.0967) < 1e-3


def test_xirr_with_intermediate_withdrawal():
    # -10000 @t0, +500 分红回流 @0.5y, 市值10500 @1y
    r = xirr(
        [("2025-01-01", -10000.0), ("2025-07-01", 500.0)],
        "2026-01-01",
        10500.0,
    )
    assert 0.09 < r < 0.11
