"""Cross-venue paper CLI tests: the per-run advisory render, the DEBOUNCED persistence-gated alerts over the log
(only a persistent tripwire surfaces -- a one-run blip or a single 429 never fires), and the parquet log append."""
from __future__ import annotations

import pandas as pd

from hedge_fund.cli.cross_venue_paper import (
    _exit_code,
    append_log,
    evaluate_paper_alerts,
    format_paper_alert_lines,
    render_advisory,
)

_SNAP = {
    "BTC": {"position": -1.0, "long_venue": "binance", "short_venue": "hyperliquid", "leg_notional": 5_000.0,
            "annualized_diff": -0.30, "expected_daily_carry": 8.2e-4, "roundtrip_bps": 12.0, "recency_ok": True,
            "friction_ok": True, "tripwire": "OK", "recency_diff": -0.30, "asof": pd.Timestamp("2026-07-30")},
    "ETH": {"position": -1.0, "long_venue": "binance", "short_venue": "hyperliquid", "leg_notional": 5_000.0,
            "annualized_diff": -0.05, "expected_daily_carry": 1.4e-4, "roundtrip_bps": 80.0, "recency_ok": True,
            "friction_ok": False, "tripwire": "WARN", "recency_diff": -0.05, "asof": pd.Timestamp("2026-07-30")},
}

# An ERROR snapshot entry (one asset could not be fetched -- a transient network/data error).
_SNAP_ERR = {
    "BTC": {"tripwire": "ERROR", "error": "HTTP Error 429: Too Many Requests", "asof": pd.Timestamp("2026-07-31")},
    "ETH": {**_SNAP["BTC"]},   # a normal OK entry
}


def _mklog(asset_statuses: dict) -> pd.DataFrame:
    """Build a paper log (asset, tripwire, asof) from {asset: [status, ...]} chronological (oldest first)."""
    base = pd.Timestamp("2026-07-01", tz="UTC")
    rows = [{"asset": a, "tripwire": st, "asof": base + pd.Timedelta(days=i)}
            for a, seq in asset_statuses.items() for i, st in enumerate(seq)]
    return pd.DataFrame(rows)


# --- per-run advisory (stdout, current state, not debounced) ---------------

def test_render_advisory_lists_each_asset_leg_and_tripwire():
    text = "\n".join(render_advisory(_SNAP))
    assert "BTC" in text and "ETH" in text
    assert "long binance" in text.lower() and "short hyperliquid" in text.lower()   # the delta-neutral legs
    assert "OK" in text and "WARN" in text                                          # per-asset tripwire status


def test_render_advisory_labels_an_error_entry_distinctly():
    text = "\n".join(render_advisory(_SNAP_ERR))
    assert "BTC" in text and "DATA/NETWORK error" in text and "429" in text          # no KeyError on the sparse row


# --- debounced persistence-gated alerts (alerts.md) ------------------------

def test_a_single_warn_run_does_not_fire():
    assert evaluate_paper_alerts(_mklog({"BTC": ["OK", "WARN"]}), warn_persistence=3) == []


def test_persistent_warn_fires():
    recs = evaluate_paper_alerts(_mklog({"BTC": ["OK", "WARN", "WARN", "WARN"]}), warn_persistence=3)
    assert len(recs) == 1 and recs[0]["asset"] == "BTC" and recs[0]["severity"] == "WARN"


def test_a_warn_streak_broken_by_a_healthy_run_does_not_fire():
    assert evaluate_paper_alerts(_mklog({"BTC": ["WARN", "WARN", "OK"]}), warn_persistence=3) == []


def test_persistent_fail_fires_fail():
    recs = evaluate_paper_alerts(_mklog({"ETH": ["FAIL", "FAIL"]}), alert_persistence=2, warn_persistence=3)
    assert len(recs) == 1 and recs[0]["severity"] == "FAIL"


def test_a_one_off_error_is_a_blip_not_an_alert():
    # A single 429 (the exact failure the full-cycle verification surfaced) must NOT spam alerts.md.
    assert evaluate_paper_alerts(_mklog({"BTC": ["OK", "OK", "ERROR"]}), warn_persistence=3) == []


def test_a_persistent_data_outage_escalates_to_warn():
    recs = evaluate_paper_alerts(_mklog({"BTC": ["ERROR", "ERROR", "ERROR"]}), warn_persistence=3)
    assert len(recs) == 1 and recs[0]["severity"] == "WARN"      # a real outage (not a blip) surfaces


def test_format_paper_alert_lines_grammar():
    recs = [{"asset": "BTC", "severity": "WARN", "consecutive": 3, "latest_status": "WARN",
             "latest_date": pd.Timestamp("2026-07-31", tz="UTC")}]
    line = format_paper_alert_lines(recs, now=pd.Timestamp("2026-07-31", tz="UTC"))[0]
    assert "WARN  cross_venue_paper:BTC" in line and "3 consecutive runs" in line


def test_exit_code_maps_debounced_severity():
    assert _exit_code([]) == 0                                              # clean / not-yet-persistent
    assert _exit_code([{"severity": "WARN"}]) == 1
    assert _exit_code([{"severity": "FAIL"}, {"severity": "WARN"}]) == 2    # FAIL takes precedence


# --- the parquet log --------------------------------------------------------

def test_append_log_writes_one_row_per_asset(tmp_path):
    p = tmp_path / "log.parquet"
    append_log(_SNAP, p)
    df = pd.read_parquet(p)
    assert set(df["asset"]) == {"BTC", "ETH"} and len(df) == 2
    append_log(_SNAP, p)                                 # second run appends, does not overwrite
    assert len(pd.read_parquet(p)) == 4


def test_append_log_handles_the_sparse_error_row(tmp_path):
    p = tmp_path / "log.parquet"
    append_log(_SNAP_ERR, p)                             # the ERROR row has fewer keys -> must not crash
    df = pd.read_parquet(p)
    assert set(df["asset"]) == {"BTC", "ETH"} and "error" in df.columns
