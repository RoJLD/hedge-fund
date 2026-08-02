"""Cross-venue testnet CLI: dry-run places nothing (no keys), the per-venue cap guard refuses oversized legs,
and an armed probe with injected FakeTestnetVenue reports OK -> exit 0. No network, no keys, no real orders."""
from __future__ import annotations

import pytest

from hedge_fund.cli.cross_venue_testnet import _cap_guard, main
from hedge_fund.execution.venue import FakeTestnetVenue

_DECISION = {"position": -1.0, "long_venue": "binance", "short_venue": "hyperliquid", "leg_notional": 50.0}


def test_dry_run_places_nothing_and_returns_0(capsys):
    rc = main(["--mode", "probe"], decision=_DECISION)          # no --arm -> dry-run, needs no venues/keys
    out = capsys.readouterr().out
    assert rc == 0 and "DRY-RUN" in out and "placed nothing" in out.lower()


def test_cap_guard_refuses_an_oversized_leg():
    with pytest.raises(SystemExit):
        _cap_guard(leg_notional=1000.0, cap=100.0)


def test_armed_probe_with_injected_fakes_reports_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("hedge_fund.cli.cross_venue_testnet._LOG", tmp_path / "session_log.parquet")
    venues = {"binance": FakeTestnetVenue("binance", mid_px=100.0),
              "hyperliquid": FakeTestnetVenue("hyperliquid", mid_px=100.0)}
    rc = main(["--arm", "--mode", "probe"], venues=venues, decision=_DECISION)
    assert rc == 0                                              # reconcile OK -> exit 0
    assert (tmp_path / "session_log.parquet").exists()
