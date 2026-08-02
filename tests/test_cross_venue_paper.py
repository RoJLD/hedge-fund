"""Cross-venue paper assessment tests (pure). Friction from the observed books + the two tripwires (recency:
recent Δf must stay > threshold; friction-envelope: live round-trip friction must stay <= the exp082-085 envelope)."""
from __future__ import annotations

import pandas as pd

from hedge_fund.deploy.cross_venue.paper import assess_snapshot, paper_snapshot

# mid 100 with a realistic ~1 bp half-spread, deep enough that $5k fills at the touch -> ~11 bps/leg round-trip
# (well under the 50 bps envelope). (The prior 99/101 fixture was a 100 bps half-spread -> ~418 bps -> not healthy.)
_BOOK = {"bids": [(99.99, 1000.0), (99.98, 2000.0)], "asks": [(100.01, 1000.0), (100.02, 2000.0)]}
_DECISION = {"position": -1.0, "long_venue": "binance", "short_venue": "hyperliquid",
             "leg_notional": 5_000.0, "annualized_diff": -0.30, "expected_daily_carry": 8.2e-4}


def test_healthy_snapshot_passes_both_tripwires():
    books = {"long": _BOOK, "short": _BOOK}
    out = assess_snapshot(_DECISION, books, taker_fee_bps=4.5, friction_envelope_bps=50.0,
                          recency_diff=-0.30, recency_threshold=0.0)
    assert out["roundtrip_bps"] > 0
    assert out["recency_ok"] is True                # |Δf| 0.30 > 0 threshold (differential alive, short side)
    assert out["friction_ok"] is True               # deep book -> round-trip well under the 50 bps envelope
    assert out["tripwire"] == "OK"


def test_recency_fires_when_differential_compresses():
    books = {"long": _BOOK, "short": _BOOK}
    # recency uses the ABSOLUTE differential magnitude (the carry earns |Δf| regardless of sign); ~0 -> compressed.
    out = assess_snapshot(_DECISION, books, taker_fee_bps=4.5, friction_envelope_bps=50.0,
                          recency_diff=0.0, recency_threshold=0.01)
    assert out["recency_ok"] is False
    assert out["tripwire"] in ("WARN", "FAIL")


def test_friction_fires_above_the_envelope():
    thin = {"bids": [(99.0, 0.05)], "asks": [(101.0, 0.05)]}   # tiny depth -> filling 5k walks far beyond book
    books = {"long": thin, "short": thin}
    out = assess_snapshot(_DECISION, books, taker_fee_bps=4.5, friction_envelope_bps=50.0,
                          recency_diff=-0.30, recency_threshold=0.0)
    assert out["friction_ok"] is False
    assert out["tripwire"] in ("WARN", "FAIL")


def test_friction_fires_on_unfillable_size_even_if_touch_is_tight():
    # A TIGHT (1 bp) but SHALLOW book: the $5k leg fills only ~$0.5 at the touch -> low in-book slippage but almost
    # entirely UNFILLED. Without the unfilled guard this would read false-healthy (friction_ok=True); it must fire.
    shallow = {"bids": [(99.99, 0.005)], "asks": [(100.01, 0.005)]}   # ~$0.5 depth per side vs the $5k leg
    books = {"long": shallow, "short": shallow}
    out = assess_snapshot(_DECISION, books, taker_fee_bps=4.5, friction_envelope_bps=50.0,
                          recency_diff=-0.30, recency_threshold=0.0)
    assert out["unfilled_notional"] > 0.0
    assert out["friction_ok"] is False
    assert out["tripwire"] in ("WARN", "FAIL")


_DEEP_BOOK = {"perp": {"bids": [(99.99, 1000.0)], "asks": [(100.01, 1000.0)]}}   # deep enough a $5k leg fills


def test_paper_snapshot_isolates_a_per_asset_fetch_failure(monkeypatch):
    # A daily unattended monitor must not crash when ONE asset's live fetch fails (e.g. HTTP 429): that asset is
    # marked ERROR (a data/network could-not-check, NOT a strategy tripwire) and the OTHER asset is still checked.
    import hedge_fund.deploy.cross_venue.paper as paper_mod

    def fake_diff(a, **kw):
        if a == "BTC":
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return pd.Series([-0.30] * 10, index=pd.date_range("2026-01-01", periods=10, freq="D"))

    monkeypatch.setattr(paper_mod, "cross_venue_diff", fake_diff)
    monkeypatch.setattr("quant_marketdata.live_quotes.fetch_leg_books", lambda symbols, **kw: _DEEP_BOOK)

    out = paper_snapshot(["BTC", "ETH"], notional=10_000.0, taker_fee_bps=4.5, friction_envelope_bps=50.0)
    assert out["BTC"]["tripwire"] == "ERROR" and "429" in out["BTC"]["error"]   # failure isolated + labeled
    assert out["ETH"]["tripwire"] in ("OK", "WARN", "FAIL")                      # the other asset still checked
