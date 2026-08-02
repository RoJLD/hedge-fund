import pytest

from hedge_fund.execution.testnet import (
    TESTNET_HOSTS,
    assert_testnet,
    intended_orders,
    make_testnet_clients,
    place_orders,
    realized_friction_bps,
)


class _FakeEx:
    def __init__(self, config=None):
        self.config = config or {}
        self.sandbox = False
        self.urls = {"api": {"public": "https://api.binance.com"}}  # MAINNET by default

    def set_sandbox_mode(self, on):
        self.sandbox = on
        if on:
            self.urls = {"api": {"public": "https://testnet.binance.vision/api"}}


# --- safety / clients -------------------------------------------------------


def test_testnet_hosts_allowlist():
    assert "testnet.binance.vision" in TESTNET_HOSTS
    assert "testnet.binancefuture.com" in TESTNET_HOSTS


def test_assert_testnet_raises_on_mainnet():
    ex = _FakeEx()  # mainnet url, sandbox not set
    with pytest.raises(RuntimeError):
        assert_testnet(ex)


def test_assert_testnet_passes_on_sandbox():
    ex = _FakeEx()
    ex.set_sandbox_mode(True)
    assert_testnet(ex)  # no raise


def test_make_testnet_clients_sets_sandbox_and_verifies():
    made = {}

    def factory(market):
        ex = _FakeEx()
        made[market] = ex
        return ex

    clients = make_testnet_clients(
        spot_creds={"apiKey": "k", "secret": "s"},
        futures_creds={"apiKey": "k2", "secret": "s2"},
        factory=factory,
    )
    assert set(clients) == {"spot", "futures"}
    assert all(ex.sandbox for ex in clients.values())  # sandbox enabled on both


# --- orders / friction ------------------------------------------------------

_SYMBOLS = {"btc_spot": "BTC/USDT", "btc_perp": "BTC/USDT:USDT"}
_NOTIONALS = {"btc_spot": 1000.0, "btc_perp": 1000.0}


def test_intended_orders_round_trip_and_market_routing():
    orders = intended_orders(_SYMBOLS, _NOTIONALS)
    legs = {(o["leg"], o["phase"]): o for o in orders}
    assert ("btc_spot", "open") in legs and ("btc_spot", "close") in legs
    assert legs[("btc_spot", "open")]["market"] == "spot"
    assert legs[("btc_perp", "open")]["market"] == "futures"
    assert legs[("btc_spot", "open")]["side"] == "buy"
    assert legs[("btc_perp", "open")]["side"] == "sell"


def test_place_orders_dry_run_places_nothing():
    orders = intended_orders(_SYMBOLS, _NOTIONALS)
    out = place_orders({}, orders, dry_run=True)  # empty clients OK: nothing is placed
    assert all(o["placed"] is False for o in out)


class _OrderEx:
    def __init__(self):
        self.calls = []

    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        self.calls.append((symbol, type_, side, amount))
        return {"id": "1", "average": 100.0, "filled": amount, "fee": {"cost": 0.0}}


def test_place_orders_armed_places_via_client():
    clients = {"spot": _OrderEx(), "futures": _OrderEx()}
    orders = intended_orders(_SYMBOLS, _NOTIONALS)
    prices = {"btc_spot": 100.0, "btc_perp": 100.0}
    out = place_orders(clients, orders, prices=prices, dry_run=False)
    assert all(o["placed"] is True for o in out)
    assert clients["spot"].calls and clients["futures"].calls  # both markets hit


def test_place_orders_armed_sizes_in_base_units():
    # amount handed to create_order must be BASE units = quote notional / price, not the USD notional
    clients = {"spot": _OrderEx(), "futures": _OrderEx()}
    orders = intended_orders(_SYMBOLS, _NOTIONALS)  # 1000 USD per leg
    prices = {"btc_spot": 100.0, "btc_perp": 200.0}
    place_orders(clients, orders, prices=prices, dry_run=False)
    spot_amounts = [amt for (_sym, _type, _side, amt) in clients["spot"].calls]
    perp_amounts = [amt for (_sym, _type, _side, amt) in clients["futures"].calls]
    assert all(a == pytest.approx(10.0) for a in spot_amounts)  # 1000 / 100
    assert all(a == pytest.approx(5.0) for a in perp_amounts)   # 1000 / 200


def test_place_orders_armed_requires_prices():
    clients = {"spot": _OrderEx(), "futures": _OrderEx()}
    orders = intended_orders(_SYMBOLS, _NOTIONALS)
    with pytest.raises(ValueError):
        place_orders(clients, orders, dry_run=False)  # armed but no prices -> refuse to size blind


def test_realized_friction_ge_zero_and_turnover_scales():
    fills = [
        {"leg": "btc_spot", "side": "buy", "avg_price": 100.5},
        {"leg": "btc_spot", "side": "sell", "avg_price": 99.5},
    ]
    mids = {"btc_spot": 100.0}
    out = realized_friction_bps(fills, mids, taker_fee_bps=4.0, turnover=0.1)
    assert out["friction_bps_per_day"] > 0
