"""Cross-venue carry decision engine (deploy Stage 1). Pure, no network/keys: given the annualized funding-
differential history Δf (Binance - Hyperliquid), compute TODAY's delta-neutral target -- the carry position
sign(MA_k(Δf)) evaluated at the last row (NOT differential_carry_frame's last row, which its forward-return dropna
removes), the long/short venue orientation (position<0 -> long Binance / short Hyperliquid, exp082 convention), the
per-leg notional (0.5*leverage*notional), and the expected daily carry. Shared by every deployment stage."""
from __future__ import annotations

import numpy as np
import pandas as pd

_DAYS = 365


def decide(diff: pd.Series, *, k: int = 7, notional: float, leverage: float = 1.0) -> dict:
    """Today's delta-neutral cross-venue target from the annualized Δf history. `notional` = the book size (USD);
    each leg trades 0.5*leverage*notional. Raises ValueError if there is not enough history for the MA_k."""
    d = diff.dropna().astype(float)
    if len(d) < k:
        raise ValueError(f"need >= k={k} Δf observations, got {len(d)}")
    position = float(np.sign(d.rolling(k).mean().iloc[-1]))            # TODAY's target (last available MA_k)
    today_diff = float(d.iloc[-1])
    long_is_bn = position < 0                                          # position<0 -> long Binance / short HL
    return {
        "position": position,
        "long_venue": "binance" if long_is_bn else "hyperliquid",
        "short_venue": "hyperliquid" if long_is_bn else "binance",
        # position 0 (MA_k exactly 0 -- a fully compressed differential, no signal) is FLAT: no leg, not a phantom
        # 0.5*leverage*notional trade that the advisory would misreport as "pos=0 @ N USD/leg".
        "leg_notional": 0.0 if position == 0.0 else 0.5 * leverage * notional,
        "annualized_diff": today_diff,
        "expected_daily_carry": position * today_diff / _DAYS,
    }
