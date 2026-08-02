"""BinanceTestnetVenue: wraps the existing ccxt-sandbox execution/testnet.py. Tests use a FAKE ccxt client
(no network, no keys) and assert (a) testnet-only guard raises on a mainnet URL, (b) base-unit sizing."""
from __future__ import annotations

import pytest

from hedge_fund.execution.binance_testnet import BinanceTestnetVenue


class _FakeCcxt:
    def __init__(self, api_url):
        self.urls = {"api": api_url}
        self.last_order = None

    def create_order(self, symbol, otype, side, amount, price, params):
        self.last_order = {"symbol": symbol, "type": otype, "side": side, "amount": amount}
        return {"id": "1", "average": 100.0, "filled": amount, "fee": {"cost": 0.4}}


def test_assert_testnet_raises_on_a_mainnet_url():
    v = BinanceTestnetVenue(_FakeCcxt("https://fapi.binance.com"))     # NOT a testnet host
    with pytest.raises(RuntimeError, match="testnet"):
        v.assert_testnet()


def test_assert_testnet_passes_on_a_testnet_url():
    v = BinanceTestnetVenue(_FakeCcxt("https://testnet.binancefuture.com"))
    v.assert_testnet()                                                  # does not raise


def test_place_market_sizes_base_amount_from_notional():
    ex = _FakeCcxt("https://testnet.binancefuture.com")
    v = BinanceTestnetVenue(ex)
    r = v.place_market("BTC/USDT:USDT", "sell", 1000.0, 100.0, dry_run=False)
    assert ex.last_order["amount"] == pytest.approx(10.0)               # 1000 / 100 base units
    assert r["placed"] is True and r["ok"] is True and r["avg_price"] == 100.0


def test_dry_run_places_nothing():
    ex = _FakeCcxt("https://testnet.binancefuture.com")
    v = BinanceTestnetVenue(ex)
    r = v.place_market("BTC/USDT:USDT", "sell", 1000.0, 100.0, dry_run=True)
    assert r["placed"] is False and ex.last_order is None
