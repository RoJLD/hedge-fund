"""Carry testnet execution adapter (credential-gated, TESTNET-ONLY, dry-run-default).

Produces EMPIRICAL realized friction from REAL fills on the exchange testnet -- the real-fill
counterpart to quant_marketdata.paper_execution's modeled friction -- to feed the carry cost tripwire.
SAFETY: testnet-only by construction (set_sandbox_mode + testnet-URL allow-list that RAISES
otherwise; NO mainnet code path here), dry-run by default (places nothing unless armed), keys
from env only. Live/mainnet execution is a separate, strongly-gated step (not in this module).
"""

from __future__ import annotations

from quant_marketdata.paper_execution import slippage_bps

TESTNET_HOSTS = frozenset({"testnet.binance.vision", "testnet.binancefuture.com"})


def assert_testnet(ex) -> None:
    """Raise unless the client's api URL host is on the testnet allow-list (defence-in-depth)."""
    urls = str(getattr(ex, "urls", {}).get("api", ""))
    if not any(host in urls for host in TESTNET_HOSTS):
        raise RuntimeError(
            f"refusing to operate: client api URL is not a known testnet host ({urls!r}); "
            "this scaffold is testnet-only"
        )


def _default_factory(venue: str):
    import ccxt

    def factory(market: str):
        return getattr(ccxt, venue)({"options": {"defaultType": market}, "enableRateLimit": True})

    return factory


def make_testnet_clients(
    *, spot_creds, futures_creds, venue: str = "binance", factory=None
) -> dict:
    """Build sandboxed (testnet) ccxt clients for spot + futures, each verified testnet-only.

    ``*_creds`` = {"apiKey":..., "secret":...} (from env, never hardcoded). ``factory`` is
    injectable (market -> client) for tests so no network/keys are needed.
    """
    factory = factory or _default_factory(venue)
    clients = {}
    for market, creds in (("spot", spot_creds), ("futures", futures_creds)):
        ex = factory(market)
        ex.config = {**getattr(ex, "config", {}), **creds}
        for k, v in creds.items():
            setattr(ex, k, v)
        ex.set_sandbox_mode(True)
        assert_testnet(ex)
        clients[market] = ex
    return clients


def _market_of(symbol: str) -> str:
    """Perp symbols carry a settlement suffix ('BTC/USDT:USDT') -> futures; else spot."""
    return "futures" if ":" in symbol else "spot"


def intended_orders(symbols: dict, notionals: dict) -> list[dict]:
    """Round-trip carry plan: open (buy spot / sell perp) then close (reverse) per leg. Pure."""
    open_side = {"spot": "buy", "futures": "sell"}  # carry = long spot, short perp
    close_side = {"buy": "sell", "sell": "buy"}
    out: list[dict] = []
    for leg, symbol in symbols.items():
        market = _market_of(symbol)
        o_side = open_side[market]
        for phase, side in (("open", o_side), ("close", close_side[o_side])):
            out.append(
                {
                    "leg": leg,
                    "symbol": symbol,
                    "market": market,
                    "phase": phase,
                    "side": side,
                    "notional": float(notionals[leg]),
                }
            )
    return out


def place_orders(
    clients: dict, orders: list[dict], *, prices: dict | None = None, dry_run: bool = True
) -> list[dict]:
    """Dry-run (default): return the plan with ``placed=False``, placing nothing. Armed: place
    market orders on the routed testnet client and return fill reports.

    ``prices`` (leg -> current price) is REQUIRED when armed: ccxt market-order ``amount`` is in BASE
    units, so the order size is ``notional / price`` (quote USD -> base coin). Passing the raw USD
    notional as ``amount`` would submit e.g. a 1000-BTC order for a $1000 leg. Armed without a price
    for a leg raises rather than sizing blind."""
    out: list[dict] = []
    for o in orders:
        if dry_run:
            out.append({**o, "placed": False})
            continue
        if prices is None or o["leg"] not in prices or not prices[o["leg"]]:
            raise ValueError(
                f"armed place_orders requires a positive price for leg {o['leg']!r} to size the base "
                "amount (amount = notional / price); refusing to size blind"
            )
        ex = clients[o["market"]]
        amount = float(o["notional"]) / float(prices[o["leg"]])  # BASE units = quote notional / price
        report = ex.create_order(o["symbol"], "market", o["side"], amount, None, {})
        out.append(
            {
                "leg": o["leg"],
                "phase": o["phase"],
                "side": o["side"],
                "order_id": report.get("id"),
                "avg_price": report.get("average"),
                "filled": report.get("filled"),
                "fee": (report.get("fee") or {}).get("cost", 0.0),
                "placed": True,
            }
        )
    return out


def realized_friction_bps(
    fills: list[dict], mids: dict, taker_fee_bps: float, *, turnover: float
) -> dict:
    """Empirical realized friction (bps/day on gross) from ACTUAL fills vs mids + fees.

    Same {friction_bps_per_day, per_leg} shape as quant_marketdata.paper_execution.simulate_carry_friction,
    so it drops into the same tripwire comparison (empirical vs modeled vs floor)."""
    per_leg: dict = {}
    for f in fills:
        mid = mids[f["leg"]]
        slip = slippage_bps(f["avg_price"], mid, side=f["side"])
        per_leg.setdefault(f["leg"], 0.0)
        per_leg[f["leg"]] += slip + taker_fee_bps
    modeled = turnover * sum(per_leg.values())
    return {"friction_bps_per_day": float(modeled), "per_leg": per_leg, "n_fills": len(fills)}
