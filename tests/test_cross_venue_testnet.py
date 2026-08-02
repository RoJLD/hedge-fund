"""Cross-venue testnet orchestrator, end-to-end with injected FakeTestnetVenue (no network, no keys): leg orders,
place-both (incl. a one-leg-fails NAKED path), reconciliation tolerance, round-trip friction, probe + hold modes."""
from __future__ import annotations

import datetime
import json
import math

import pytest

from hedge_fund.deploy.cross_venue.testnet import (
    build_leg_orders,
    place_both,
    reconcile,
    run_hold_close,
    run_hold_open,
    run_probe,
)
from hedge_fund.execution.venue import FakeTestnetVenue

_DECISION = {"position": -1.0, "long_venue": "binance", "short_venue": "hyperliquid", "leg_notional": 500.0}
_SYMBOLS = {"binance": "BTC/USDT:USDT", "hyperliquid": "BTC"}


def _venues(*, hl_fail=False):
    return {"binance": FakeTestnetVenue("binance", mid_px=100.0),
            "hyperliquid": FakeTestnetVenue("hyperliquid", mid_px=100.0, fail=hl_fail)}


def test_build_leg_orders_long_buys_short_sells():
    lo, so = build_leg_orders(_DECISION, _SYMBOLS)
    assert lo["venue"] == "binance" and lo["side"] == "buy" and lo["symbol"] == "BTC/USDT:USDT"
    assert so["venue"] == "hyperliquid" and so["side"] == "sell" and so["symbol"] == "BTC"
    assert lo["notional"] == 500.0 and so["notional"] == 500.0


def test_reconcile_ok_when_both_fill_delta_neutral():
    lf, sf = place_both(_venues(), *build_leg_orders(_DECISION, _SYMBOLS), dry_run=False)
    rec = reconcile(lf, sf, tolerance=1.0)
    assert rec["status"] == "OK" and rec["imbalance_usd"] == pytest.approx(0.0, abs=1e-6)


def test_reconcile_naked_when_one_leg_fails_and_place_both_does_not_crash():
    # HL raises -> place_both captures it (report never crash) -> reconcile flags NAKED.
    lf, sf = place_both(_venues(hl_fail=True), *build_leg_orders(_DECISION, _SYMBOLS), dry_run=False)
    assert sf["ok"] is False and "error" in sf
    assert reconcile(lf, sf, tolerance=1.0)["status"] == "NAKED"


def test_probe_round_trip_reports_reconcile_and_friction():
    out = run_probe(_venues(), _DECISION, _SYMBOLS, tolerance=1.0, taker_fee_bps=4.0, dry_run=False)
    assert out["mode"] == "probe"
    assert out["reconcile"]["status"] == "OK"
    assert out["friction_bps"]["long"] == pytest.approx(8.0)   # 0 slippage (fill==mid) + 2*4 bps fee


def test_hold_open_persists_state_and_close_reads_and_clears_it(tmp_path):
    state = tmp_path / "open_position.json"
    run_hold_open(_venues(), _DECISION, _SYMBOLS, state_path=state, dry_run=False)
    assert state.exists() and "open_fills" in json.loads(state.read_text())
    out = run_hold_close(_venues(), _SYMBOLS, state_path=state, tolerance=1.0, taker_fee_bps=4.0, dry_run=False)
    assert out["mode"] == "hold-close" and out["reconcile"]["status"] == "OK"
    assert not state.exists()                                   # armed close clears the state


def test_hold_open_refuses_if_a_position_is_already_open(tmp_path):
    state = tmp_path / "open_position.json"
    state.write_text("{}")
    with pytest.raises(SystemExit):
        run_hold_open(_venues(), _DECISION, _SYMBOLS, state_path=state, dry_run=False)


def test_hold_open_persists_a_parseable_utc_timestamp(tmp_path):
    state = tmp_path / "open_position.json"
    run_hold_open(_venues(), _DECISION, _SYMBOLS, state_path=state, dry_run=False)
    ts = json.loads(state.read_text())["ts"]
    assert isinstance(ts, str) and ts
    datetime.datetime.fromisoformat(ts)                          # raises if unparseable


def test_place_both_missing_venue_key_degrades_to_naked_not_crash():
    # short leg routes to "hyperliquid", which is absent from `venues` -> must not raise a KeyError.
    venues = {"binance": FakeTestnetVenue("binance", mid_px=100.0)}
    lf, sf = place_both(venues, *build_leg_orders(_DECISION, _SYMBOLS), dry_run=False)
    assert sf["ok"] is False and "error" in sf
    assert reconcile(lf, sf, tolerance=1.0)["status"] == "NAKED"


def test_reconcile_imbalanced_when_notionals_differ_beyond_tolerance():
    long_fill = {"ok": True, "placed": True, "filled": 5.0, "avg_price": 100.0}
    short_fill = {"ok": True, "placed": True, "filled": 5.0, "avg_price": 110.0}
    rec = reconcile(long_fill, short_fill, tolerance=1.0)
    assert rec["status"] == "IMBALANCED" and rec["imbalance_usd"] == pytest.approx(50.0)


def test_probe_halts_the_close_on_a_naked_open():
    # open short (HL) fails -> NAKED open -> HALT: no close legs placed (no auto-unwind), NaN friction.
    out = run_probe(_venues(hl_fail=True), _DECISION, _SYMBOLS, tolerance=1.0, taker_fee_bps=4.0, dry_run=False)
    assert out["reconcile"]["status"] == "NAKED"
    assert out["close"] is None and out["halted"] == "NAKED"
    assert math.isnan(out["friction_bps"]["long"]) and math.isnan(out["friction_bps"]["short"])


def test_hold_open_does_not_persist_a_naked_open(tmp_path):
    state = tmp_path / "open_position.json"
    out = run_hold_open(_venues(hl_fail=True), _DECISION, _SYMBOLS, state_path=state, dry_run=False)
    assert out["reconcile"]["status"] == "NAKED"
    assert not state.exists()                        # a half-open is NOT recorded as a hold
