"""HyperliquidTestnetVenue -- an ExecutionVenue over the Hyperliquid TESTNET via hyperliquid-python-sdk (EIP-712
signing with an agent key). Testnet-only by construction: assert_testnet RAISES unless the SDK base_url is the HL
testnet URL; no mainnet code path. The agent key (when armed) comes from env only. HL symbols are coin names."""
from __future__ import annotations

import os

HL_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


class HyperliquidTestnetVenue:
    """ExecutionVenue for Hyperliquid testnet. `exchange` = an HL SDK Exchange (signs+places), `info` = an HL SDK
    Info (reads mids), both built against the testnet base_url (or doubles in tests)."""

    name = "hyperliquid"

    def __init__(self, exchange, info, *, base_url: str) -> None:
        self._ex = exchange
        self._info = info
        self._base_url = base_url

    @classmethod
    def from_env(cls, *, exchange_factory=None) -> "HyperliquidTestnetVenue":
        """Build testnet SDK clients from the agent key in env (called only when the CLI is armed)."""
        agent_key = os.environ.get("QUANTLAB_TESTNET_HL_AGENT_KEY")
        if not agent_key:
            raise SystemExit("--arm requires QUANTLAB_TESTNET_HL_AGENT_KEY in the environment")
        if exchange_factory is not None:
            exchange, info = exchange_factory(agent_key, HL_TESTNET_URL)
        else:  # pragma: no cover -- real SDK path, exercised only under QUANTLAB_SLOW_TESTS with real keys
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            wallet = Account.from_key(agent_key)
            exchange = Exchange(wallet, HL_TESTNET_URL)
            info = Info(HL_TESTNET_URL, skip_ws=True)
        return cls(exchange, info, base_url=HL_TESTNET_URL)

    def assert_testnet(self) -> None:
        if self._base_url != HL_TESTNET_URL:
            raise RuntimeError(
                f"refusing to operate: HL base_url {self._base_url!r} is not the testnet URL {HL_TESTNET_URL!r}; "
                "this adapter is testnet-only"
            )

    def mid(self, symbol: str) -> float:
        return float(self._info.all_mids()[symbol])

    def place_market(self, symbol: str, side: str, notional: float, price: float, *, dry_run: bool = True) -> dict:
        base = {"symbol": symbol, "side": side, "notional": float(notional)}
        if dry_run:
            return {**base, "avg_price": None, "filled": 0.0, "fee": 0.0, "placed": False, "ok": True}
        sz = float(notional) / float(price)           # HL order size is in base (coin) units
        rep = self._ex.market_open(symbol, side == "buy", sz)
        st = rep["response"]["data"]["statuses"][0]["filled"]
        return {**base, "avg_price": float(st["avgPx"]), "filled": float(st["totalSz"]),
                "fee": float(st.get("fee", 0.0)), "placed": True, "ok": True}
