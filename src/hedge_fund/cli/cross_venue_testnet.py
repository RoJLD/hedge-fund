"""Cross-venue carry TESTNET execution runner (deploy Stage 2) -- TESTNET-ONLY, dry-run-default, --arm-gated.

Default = DRY-RUN: prints the intended delta-neutral orders and places NOTHING (needs no keys). With --arm: reads
testnet keys from env, builds testnet-verified venues, runs the chosen mode (probe | hold-open | hold-close),
reconciles, appends a session row to results/carry_testnet/session_log.parquet, and prints a summary. SAFETY:
testnet-only (each venue assert_testnet RAISES on a non-testnet endpoint), a hard per-leg cap, keys from env only.
The AI never provisions keys, never arms.

Env keys (only read when --arm): QUANTLAB_TESTNET_BINANCEFUTURES_KEY/_SECRET, QUANTLAB_TESTNET_HL_AGENT_KEY.

Usage::
    python -m hedge_fund.cli.cross_venue_testnet                        # dry-run probe, places nothing
    python -m hedge_fund.cli.cross_venue_testnet --arm --mode probe     # places on testnet (needs keys)
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd
import yaml

from hedge_fund.deploy.cross_venue.engine import decide
from hedge_fund.deploy.cross_venue.testnet import (
    build_leg_orders,
    run_hold_close,
    run_hold_open,
    run_probe,
)
from hedge_fund.paths import ROOT

_CONFIG = ROOT / "src" / "hedge_fund" / "deploy" / "cross_venue" / "testnet_config.yaml"
_LOG = ROOT / "results" / "carry_testnet" / "session_log.parquet"
_STATE = ROOT / "results" / "carry_testnet" / "open_position.json"


def _cap_guard(*, leg_notional: float, cap: float) -> None:
    if leg_notional > cap:
        raise SystemExit(f"refusing to arm: leg notional {leg_notional} exceeds the per-venue cap {cap}")


def _live_decision(cfg: dict, asset: str) -> dict:
    from quant_marketdata.funding_diff import cross_venue_diff
    diff = cross_venue_diff(asset, start=cfg["start"], use_cache=False)
    return decide(diff, k=int(cfg["k"]), notional=float(cfg["notional"]), leverage=float(cfg["leverage"]))


def _flatten_session(out: dict, *, asset: str, mode: str) -> dict:
    rec = out.get("reconcile", {})
    fr = out.get("friction_bps", {})
    return {"asof": pd.Timestamp.now("UTC"), "asset": asset, "mode": mode,
            "reconcile_status": rec.get("status"), "imbalance_usd": rec.get("imbalance_usd"),
            "friction_long_bps": fr.get("long"), "friction_short_bps": fr.get("short")}


def main(argv: list[str] | None = None, *, venues=None, decision=None) -> int:
    cfg = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    p = argparse.ArgumentParser(description="Cross-venue carry testnet execution (testnet-only, dry-run-default).")
    p.add_argument("--arm", action="store_true", help="actually place orders on the TESTNET (needs env keys)")
    p.add_argument("--mode", choices=["probe", "hold-open", "hold-close"], default="probe")
    p.add_argument("--asset", choices=list(cfg["assets"]), default=cfg["assets"][0])
    args = p.parse_args(argv)

    symbols = cfg["symbols"][args.asset]
    if decision is None and args.mode != "hold-close":
        decision = _live_decision(cfg, args.asset) if args.arm else {
            "position": 0.0, "long_venue": "binance", "short_venue": "hyperliquid",
            "leg_notional": 0.5 * float(cfg["leverage"]) * float(cfg["notional"])}

    if not args.arm:
        print(f"[cross-venue-testnet] DRY-RUN ({args.mode}, {args.asset}): would place on TESTNET:")
        if args.mode != "hold-close":
            for o in build_leg_orders(decision, symbols):
                print(f"  {o['leg']:5} {o['side']:4} {o['venue']:11} {o['symbol']} (~{o['notional']:.0f} USD)")
        print("[cross-venue-testnet] placed NOTHING. Re-run with --arm + testnet keys to execute.")
        return 0

    _cap_guard(leg_notional=float(decision["leg_notional"]) if decision else 0.0, cap=float(cfg["cap"]))
    if venues is None:  # pragma: no cover -- real venue build, exercised only under real testnet keys
        from hedge_fund.execution.binance_testnet import BinanceTestnetVenue
        from hedge_fund.execution.hyperliquid_testnet import HyperliquidTestnetVenue
        venues = {"binance": BinanceTestnetVenue.from_env(), "hyperliquid": HyperliquidTestnetVenue.from_env()}
    for v in venues.values():
        v.assert_testnet()                                     # defence in depth: refuse any non-testnet endpoint

    if args.mode == "probe":
        out = run_probe(venues, decision, symbols, tolerance=float(cfg["tolerance"]),
                        taker_fee_bps=float(cfg["taker_fee_bps"]), dry_run=False)
    elif args.mode == "hold-open":
        out = run_hold_open(venues, decision, symbols, state_path=_STATE, dry_run=False)
    else:
        out = run_hold_close(venues, symbols, state_path=_STATE, tolerance=float(cfg["tolerance"]),
                             taker_fee_bps=float(cfg["taker_fee_bps"]), dry_run=False)

    _LOG.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([_flatten_session(out, asset=args.asset, mode=args.mode)])
    df = pd.concat([pd.read_parquet(_LOG), row], ignore_index=True) if _LOG.exists() else row
    df.to_parquet(_LOG)
    status = out["reconcile"]["status"]
    print(f"[cross-venue-testnet] ARMED ({args.mode}, {args.asset}): reconcile={status} "
          f"imbalance={out['reconcile'].get('imbalance_usd')}")
    print("[cross-venue-testnet] TESTNET fills -- mechanics only; testnet funding/liquidity != mainnet.")
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
