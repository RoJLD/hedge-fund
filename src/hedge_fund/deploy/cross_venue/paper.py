"""Cross-venue paper harness (deploy Stage 1) -- read-only, places NOTHING. assess_snapshot is pure (friction from
observed books via quant_marketdata.paper_execution + the two tripwires); paper_snapshot is the network wrapper
(live funding via quant_marketdata.funding_diff.cross_venue_diff + live books via quant_marketdata.live_quotes).

Note: cross_venue_diff resolves its funding cache via cache_dir/env QUANT_FUNDING_CACHE -- set it to the shared
2019+ cache so the fund and research read the same funding history."""
from __future__ import annotations

import pandas as pd
from quant_marketdata.funding_diff import cross_venue_diff
from quant_marketdata.paper_execution import leg_roundtrip_bps

from hedge_fund.deploy.cross_venue.engine import decide

# ccxt symbols per venue for the live order-book fetch (perp).
_SYMBOL = {"binance": "{a}/USDT:USDT", "hyperliquid": "{a}/USDC:USDC"}
_CCXT_VENUE = {"binance": "binance", "hyperliquid": "hyperliquid"}


def assess_snapshot(decision: dict, books: dict, *, taker_fee_bps: float, friction_envelope_bps: float,
                    recency_diff: float, recency_threshold: float = 0.0) -> dict:
    """Pure: from the target `decision` + the two leg `books` ({"long":{bids,asks}, "short":{bids,asks}}), the
    modeled round-trip friction (both legs) and the two tripwires. recency_ok = |recent Δf| > recency_threshold
    (the carry earns the ABSOLUTE differential; a compressed differential fires). friction_ok = round-trip <=
    envelope AND both legs fully fill (a partially-fillable book has low in-book slippage but leaves the order
    unfilled -- the false-healthy direction -- so any unfilled notional fires). tripwire = OK / WARN (one fires) /
    FAIL (both fire)."""
    n = decision["leg_notional"]
    per_leg = [leg_roundtrip_bps(books[leg], n, taker_fee_bps) for leg in ("long", "short")]
    rt = sum(p["roundtrip_bps"] for p in per_leg)
    unfilled = sum(p["unfilled_notional"] for p in per_leg)
    recency_ok = abs(recency_diff) > recency_threshold
    friction_ok = rt <= friction_envelope_bps and unfilled == 0.0     # unfillable size is NOT healthy friction
    fired = int(not recency_ok) + int(not friction_ok)
    tripwire = "OK" if fired == 0 else ("WARN" if fired == 1 else "FAIL")
    return {"roundtrip_bps": float(rt), "unfilled_notional": float(unfilled), "recency_ok": bool(recency_ok),
            "friction_ok": bool(friction_ok), "tripwire": tripwire}


def paper_snapshot(assets, *, notional: float, k: int = 7, taker_fee_bps: float, friction_envelope_bps: float,
                   recency_window: int = 7, recency_threshold: float = 0.005, leverage: float = 1.0,
                   start: str = "2019-01-01", use_cache: bool = False) -> dict:
    """Network wrapper: per asset, live Δf (cross_venue_diff) -> engine.decide -> live books (live_quotes) ->
    assess_snapshot. use_cache=False fetches the latest funding. Returns {asset: {**decision, **assessment}}.

    `start` MUST be the loader full-history start (2019), never a study-local truncating start: the Binance
    funding cache is SHARED with the deployed carry book (needs 2019+), so a 2023 start + use_cache=False would
    TRUNCATE it (the exp081 lesson). HL funding is 2023+ only regardless, so Δf/position are unchanged."""
    from quant_marketdata.live_quotes import fetch_leg_books
    out = {}
    for a in assets:
        try:
            diff = cross_venue_diff(a, start=start, use_cache=use_cache)
            decision = decide(diff, k=k, notional=notional, leverage=leverage)
            recency_diff = float(diff.dropna().iloc[-recency_window:].mean())
            books = {}
            for leg in ("long", "short"):
                venue = decision[f"{leg}_venue"]
                sym = _SYMBOL[venue].format(a=a)
                books[leg] = fetch_leg_books({"perp": sym}, venue=_CCXT_VENUE[venue], depth=50)["perp"]
            assessment = assess_snapshot(decision, books, taker_fee_bps=taker_fee_bps,
                                         friction_envelope_bps=friction_envelope_bps, recency_diff=recency_diff,
                                         recency_threshold=recency_threshold)
            out[a] = {**decision, **assessment, "recency_diff": recency_diff, "asof": pd.Timestamp.now("UTC")}
        except Exception as e:  # noqa: BLE001 -- a daily unattended monitor must not crash on a transient failure
            # A per-asset fetch/data failure (HTTP 429, a flaky venue, a MemoryError under pressure) is a
            # "could not check today" WARN, NOT a strategy tripwire -- mark it ERROR so the advisory/alert label
            # it as a data/network error (never misread as a recency/friction fire), the OTHER assets still get
            # checked, and the cycle degrades to WARN instead of a traceback. Tomorrow's run retries.
            out[a] = {"tripwire": "ERROR", "error": str(e), "asof": pd.Timestamp.now("UTC")}
    return out
