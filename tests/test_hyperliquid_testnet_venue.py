"""HyperliquidTestnetVenue: wraps the HL SDK. Tests inject FAKE exchange/info clients (no SDK, no network, no
keys) and assert (a) the testnet-URL guard raises on the mainnet base URL, (b) a market order is placed + parsed."""
from __future__ import annotations

import pytest

from hedge_fund.execution.hyperliquid_testnet import HL_TESTNET_URL, HyperliquidTestnetVenue


class _FakeInfo:
    def all_mids(self):
        return {"BTC": "100.0"}


class _FakeExchange:
    def __init__(self):
        self.last = None

    def market_open(self, coin, is_buy, sz, px=None, slippage=0.01):
        self.last = {"coin": coin, "is_buy": is_buy, "sz": sz}
        return {"status": "ok", "response": {"data": {"statuses": [
            {"filled": {"avgPx": "100.0", "totalSz": str(sz), "fee": "0.4"}}]}}}


def test_assert_testnet_raises_on_the_mainnet_base_url():
    v = HyperliquidTestnetVenue(_FakeExchange(), _FakeInfo(), base_url="https://api.hyperliquid.xyz")
    with pytest.raises(RuntimeError, match="testnet"):
        v.assert_testnet()


def test_assert_testnet_passes_on_the_testnet_base_url():
    v = HyperliquidTestnetVenue(_FakeExchange(), _FakeInfo(), base_url=HL_TESTNET_URL)
    v.assert_testnet()


def test_place_market_places_and_parses_the_fill():
    ex = _FakeExchange()
    v = HyperliquidTestnetVenue(ex, _FakeInfo(), base_url=HL_TESTNET_URL)
    r = v.place_market("BTC", "buy", 1000.0, 100.0, dry_run=False)
    assert ex.last["is_buy"] is True and ex.last["sz"] == pytest.approx(10.0)   # 1000/100 base
    assert r["placed"] is True and r["ok"] is True and r["avg_price"] == pytest.approx(100.0)


def test_dry_run_places_nothing():
    ex = _FakeExchange()
    v = HyperliquidTestnetVenue(ex, _FakeInfo(), base_url=HL_TESTNET_URL)
    r = v.place_market("BTC", "buy", 1000.0, 100.0, dry_run=True)
    assert r["placed"] is False and ex.last is None
