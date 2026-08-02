"""BinanceTestnetVenue -- an ExecutionVenue over Binance USDS-M futures TESTNET, wrapping the existing
execution/testnet.py ccxt-sandbox pattern (set_sandbox_mode + the TESTNET_HOSTS allow-list that RAISES on any
non-testnet URL). Testnet-only by construction; no mainnet code path. Keys (when armed) come from env only."""
from __future__ import annotations

import os

from hedge_fund.execution.testnet import assert_testnet as _assert_ccxt_testnet


class BinanceTestnetVenue:
    """ExecutionVenue for Binance USDS-M futures testnet. `client` is a sandboxed ccxt futures client (built via
    from_env, or a double in tests)."""

    name = "binance"

    def __init__(self, client) -> None:
        self._ex = client

    @classmethod
    def from_env(cls, *, factory=None) -> "BinanceTestnetVenue":
        """Build a sandboxed testnet futures client from env keys (called only when the CLI is armed)."""
        key = os.environ.get("QUANTLAB_TESTNET_BINANCEFUTURES_KEY")
        secret = os.environ.get("QUANTLAB_TESTNET_BINANCEFUTURES_SECRET")
        if not key or not secret:
            raise SystemExit("--arm requires QUANTLAB_TESTNET_BINANCEFUTURES_KEY and _SECRET in the environment")
        from hedge_fund.execution.testnet import make_testnet_clients
        clients = make_testnet_clients(
            spot_creds={"apiKey": key, "secret": secret},
            futures_creds={"apiKey": key, "secret": secret},
            factory=factory,
        )
        return cls(clients["futures"])

    def assert_testnet(self) -> None:
        _assert_ccxt_testnet(self._ex)                # raises unless the client api URL host is a testnet host

    def mid(self, symbol: str) -> float:
        t = self._ex.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close"))

    def place_market(self, symbol: str, side: str, notional: float, price: float, *, dry_run: bool = True) -> dict:
        base = {"symbol": symbol, "side": side, "notional": float(notional)}
        if dry_run:
            return {**base, "avg_price": None, "filled": 0.0, "fee": 0.0, "placed": False, "ok": True}
        amount = float(notional) / float(price)       # ccxt market amount is in BASE units = notional / price
        rep = self._ex.create_order(symbol, "market", side, amount, None, {})
        return {**base, "avg_price": rep.get("average"), "filled": rep.get("filled"),
                "fee": (rep.get("fee") or {}).get("cost", 0.0), "placed": True, "ok": True}
