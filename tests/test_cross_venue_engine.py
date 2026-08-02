"""Cross-venue paper decision-engine tests. The live target position = sign(MA_k(Δf)) at TODAY (the last row,
computed directly -- NOT differential_carry_frame's last row, which its forward-return dropna removes)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hedge_fund.deploy.cross_venue.engine import decide


def _diff(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, name="diff")


def test_negative_differential_longs_binance_shorts_hl():
    # Δf persistently negative -> MA_7 < 0 -> position -1 -> long Binance / short Hyperliquid (exp082 convention).
    d = _diff([-0.30] * 10)
    out = decide(d, k=7, notional=10_000.0)
    assert out["position"] == -1.0
    assert out["long_venue"] == "binance" and out["short_venue"] == "hyperliquid"
    assert out["leg_notional"] == 0.5 * 1.0 * 10_000.0                 # 0.5*leverage*notional
    assert np.isclose(out["annualized_diff"], -0.30)
    # expected daily carry = position * Δf(today) / 365 = (-1)*(-0.30)/365 > 0
    assert out["expected_daily_carry"] > 0


def test_positive_differential_flips_orientation():
    d = _diff([0.30] * 10)
    out = decide(d, k=7, notional=10_000.0)
    assert out["position"] == 1.0
    assert out["long_venue"] == "hyperliquid" and out["short_venue"] == "binance"
    assert out["expected_daily_carry"] > 0                             # (+1)*(+0.30)/365 > 0


def test_position_is_today_not_the_backtest_frame_last_row():
    # DISCRIMINATING fixture: today's sign(MA_7) DIFFERS from the backtest-frame's last-row sign. The frame appends
    # a forward-return shift(-1) + dropna, dropping TODAY's row, so its last MA_7 is YESTERDAY's. Here today's MA_7
    # = mean([-.1,-.1,-.1,-.1,-.1,.05,.9]) = +0.064 > 0 (+1), but yesterday's = mean([-.1x6,.05]) = -0.079 < 0 (-1).
    # Asserting the KNOWN-correct +1.0 (hard-coded, NOT re-derived from decide's own formula) catches the off-by-one:
    # a frame-routed implementation would return -1.0 and FAIL this test.
    d = _diff([-0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, 0.05, 0.9])
    assert decide(d, k=7, notional=1_000.0)["position"] == 1.0


def test_insufficient_history_raises():
    with pytest.raises(ValueError):
        decide(_diff([-0.1, -0.1, -0.1]), k=7, notional=1_000.0)      # only 3 obs < k=7


def test_leverage_scales_leg_notional():
    d = _diff([-0.30] * 10)
    assert decide(d, k=7, notional=10_000.0, leverage=2.0)["leg_notional"] == 0.5 * 2.0 * 10_000.0


def test_zero_signal_is_flat_with_no_leg():
    # MA_7 exactly 0 (a fully compressed differential) -> position 0 -> FLAT: no leg notional, zero carry -- not a
    # phantom trade the advisory would misreport as "pos=0 @ 5000 USD/leg".
    out = decide(_diff([0.0] * 10), k=7, notional=10_000.0)
    assert out["position"] == 0.0
    assert out["leg_notional"] == 0.0
    assert out["expected_daily_carry"] == 0.0
