"""Persistence-gated alert debounce (the fund's L3 paper-alert gate).

The generic ``evaluate_alert`` primitive carried as boilerplate (Quant-lab keeps its own copy for the
research L2 reconfirm alerts; both are trivially small). Fires only when the trailing ``persistence``
statuses are all in ``alert_statuses`` -> a one-run blip never alerts.
"""

from __future__ import annotations

import pandas as pd


def evaluate_alert(status_series: pd.Series, *, alert_statuses: set[str], persistence: int) -> dict:
    """Persistence-gated firing: True iff the trailing ``persistence`` statuses are all in
    ``alert_statuses``. Counts observations (rows); under a once-per-run cadence one row == one run."""
    s = status_series.dropna()
    consecutive = 0
    for v in reversed(s.tolist()):
        if v in alert_statuses:
            consecutive += 1
        else:
            break
    fired = len(s) >= persistence and consecutive >= persistence
    latest = str(s.iloc[-1]) if len(s) else None
    return {"fired": bool(fired), "consecutive": int(consecutive), "latest": latest}
