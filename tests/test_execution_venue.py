"""ExecutionVenue Protocol + FakeTestnetVenue double: the uniform surface both testnet venues implement,
and a canned double so the whole harness is testable with no network and no keys."""
from __future__ import annotations

import pytest

from hedge_fund.execution.venue import ExecutionVenue, FakeTestnetVenue


def test_fake_venue_conforms_to_protocol():
    v = FakeTestnetVenue("fake", mid_px=100.0)
    assert isinstance(v, ExecutionVenue)          # runtime_checkable Protocol
    assert v.name == "fake"
    v.assert_testnet()                            # no-op, does not raise
    assert v.mid("BTC/USDT:USDT") == 100.0


def test_fake_venue_dry_run_places_nothing():
    v = FakeTestnetVenue("fake", mid_px=100.0)
    r = v.place_market("BTC/USDT:USDT", "buy", 1000.0, 100.0, dry_run=True)
    assert r["placed"] is False and r["ok"] is True


def test_fake_venue_armed_fill_sizes_base_from_notional():
    v = FakeTestnetVenue("fake", mid_px=100.0, fill_price=100.0)
    r = v.place_market("BTC/USDT:USDT", "buy", 1000.0, 100.0, dry_run=False)
    assert r["placed"] is True and r["ok"] is True
    assert r["filled"] == pytest.approx(10.0)     # 1000 USD / 100 px = 10 base units
    assert r["avg_price"] == 100.0


def test_fake_venue_fail_flag_raises_for_the_orchestrator_to_catch():
    v = FakeTestnetVenue("fake", mid_px=100.0, fail=True)
    with pytest.raises(RuntimeError, match="simulated venue failure"):
        v.place_market("BTC/USDT:USDT", "buy", 1000.0, 100.0, dry_run=False)
