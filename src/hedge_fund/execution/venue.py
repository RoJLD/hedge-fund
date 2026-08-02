"""ExecutionVenue Protocol -- the uniform surface both testnet venues (and a later live adapter) implement --
plus FakeTestnetVenue, a canned double so the whole cross-venue harness is testable with NO network and NO keys.

A place_market return dict is {"symbol","side","notional","avg_price","filled","fee","placed","ok"} (ok=True;
placed=False under dry_run). The orchestrator wraps every venue call in try/except and records ok=False on a
raise -- that is the "report never crash" boundary -- so a venue method is free to raise on a real failure."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutionVenue(Protocol):
    name: str

    def assert_testnet(self) -> None:
        """Raise unless this client is verified testnet-only (defence in depth; no mainnet code path)."""
        ...

    def mid(self, symbol: str) -> float:
        """Current mid price for `symbol` (used to size the base amount = notional / price + as a friction ref)."""
        ...

    def place_market(self, symbol: str, side: str, notional: float, price: float, *, dry_run: bool = True) -> dict:
        """Dry-run (default): return the plan with placed=False, place nothing. Armed: place a market order sized
        base = notional / price and return the fill. `side` is "buy"/"sell"."""
        ...


class FakeTestnetVenue:
    """A canned ExecutionVenue double for tests: no network, no keys. `fail=True` raises on place_market so the
    orchestrator's report-never-crash path is exercised; otherwise fills `notional / fill_price` base units."""

    def __init__(self, name: str, *, mid_px: float, fill_price: float | None = None,
                 fee_bps: float = 4.0, fail: bool = False) -> None:
        self.name = name
        self._mid = float(mid_px)
        self._fill_price = float(fill_price if fill_price is not None else mid_px)
        self._fee_bps = float(fee_bps)
        self._fail = bool(fail)

    def assert_testnet(self) -> None:
        return None                                   # a fake is testnet by definition

    def mid(self, symbol: str) -> float:
        return self._mid

    def place_market(self, symbol: str, side: str, notional: float, price: float, *, dry_run: bool = True) -> dict:
        base = {"symbol": symbol, "side": side, "notional": float(notional)}
        if dry_run:
            return {**base, "avg_price": None, "filled": 0.0, "fee": 0.0, "placed": False, "ok": True}
        if self._fail:
            raise RuntimeError("simulated venue failure")
        filled = float(notional) / self._fill_price
        return {**base, "avg_price": self._fill_price, "filled": filled,
                "fee": float(notional) * self._fee_bps / 1e4, "placed": True, "ok": True}
