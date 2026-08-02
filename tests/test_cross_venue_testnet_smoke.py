"""Real-testnet smoke for the cross-venue Stage-2 execution adapter -- GATED, SKIPPED BY DEFAULT.

Unlike the rest of the Stage-2 suite (which runs entirely against FakeTestnetVenue), these tests exercise the REAL
Binance USDS-M futures testnet + Hyperliquid testnet through the actual venue adapters. They CANNOT run until Robin
has Hyperliquid operability (a funded HL testnet wallet + agent-key) and sets the testnet keys in env. They are
therefore skipped by default and never run in CI / the normal suite.

To run the read-only connectivity smoke (builds the real venues, asserts they are testnet, fetches real mids -- NO
orders):
    set QUANTLAB_SLOW_TESTS=1
    set QUANTLAB_TESTNET_BINANCEFUTURES_KEY / _SECRET, QUANTLAB_TESTNET_HL_AGENT_KEY
    pip install -e .[deploy]        # the hyperliquid-python-sdk

To ALSO run the armed probe (DOUBLE-GATED -- it places REAL orders on the testnets):
    additionally set QUANTLAB_TESTNET_ARM=1

The assistant never sets these flags and never provisions keys; running this is Robin's explicit, credentialed step.
"""
from __future__ import annotations

import os

import pytest


def _binance_keys() -> bool:
    return bool(
        os.environ.get("QUANTLAB_TESTNET_BINANCEFUTURES_KEY")
        and os.environ.get("QUANTLAB_TESTNET_BINANCEFUTURES_SECRET")
    )


def _hl_key() -> bool:
    return bool(os.environ.get("QUANTLAB_TESTNET_HL_AGENT_KEY"))


def _hl_sdk_installed() -> bool:
    try:
        import eth_account  # noqa: F401
        import hyperliquid  # noqa: F401
    except Exception:  # noqa: BLE001 -- the SDK is an optional .[deploy] extra; absent -> skip, not error
        return False
    return True


_CONNECT_OK = bool(os.environ.get("QUANTLAB_SLOW_TESTS")) and _binance_keys() and _hl_key() and _hl_sdk_installed()
_ARM_OK = _CONNECT_OK and bool(os.environ.get("QUANTLAB_TESTNET_ARM"))

_skip_connect = pytest.mark.skipif(
    not _CONNECT_OK,
    reason="real-testnet smoke: set QUANTLAB_SLOW_TESTS=1 + QUANTLAB_TESTNET_BINANCEFUTURES_KEY/_SECRET + "
    "QUANTLAB_TESTNET_HL_AGENT_KEY and install .[deploy]",
)
_skip_arm = pytest.mark.skipif(
    not _ARM_OK,
    reason="armed real-testnet probe: additionally set QUANTLAB_TESTNET_ARM=1 (places REAL testnet orders)",
)


@_skip_connect
def test_real_testnet_venues_are_testnet_and_quote():
    """Read-only: build the real venues from env, assert each is on a testnet endpoint, fetch a real mid. No orders."""
    from hedge_fund.execution.binance_testnet import BinanceTestnetVenue
    from hedge_fund.execution.hyperliquid_testnet import HyperliquidTestnetVenue

    binance = BinanceTestnetVenue.from_env()
    hl = HyperliquidTestnetVenue.from_env()
    binance.assert_testnet()  # must NOT raise -> a known testnet endpoint (defence in depth)
    hl.assert_testnet()
    assert binance.mid("BTC/USDT:USDT") > 0  # real testnet market data
    assert hl.mid("BTC") > 0


@_skip_arm
def test_real_testnet_armed_probe_round_trips():
    """DOUBLE-GATED -- places REAL orders on the testnets. One tiny delta-neutral probe through the real armed CLI
    path (from_env venues + live decision + place both + reconcile); it must COMPLETE (0 = reconcile OK, 1 =
    NAKED/IMBALANCED reported) without crashing -- exactly the real-fill mechanics paper cannot show."""
    from hedge_fund.cli.cross_venue_testnet import main

    rc = main(["--arm", "--mode", "probe"])
    assert rc in (0, 1)
