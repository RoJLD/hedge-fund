"""Cross-venue testnet orchestrator (deploy Stage 2): from the Stage-1 engine.decide target, build the two leg
orders, PLACE BOTH near-simultaneously (no sequencing, no auto-unwind), reconcile delta-neutral, and measure
real round-trip friction vs the modeled envelope. Report never crashes: a per-venue raise is captured as an
ok=False leg -> reconcile flags NAKED. Probe = open->close round-trip; hold = open (persist state) then a later
close. Venues are injected (ExecutionVenue), so the whole file is testable with FakeTestnetVenue -- no keys."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from quant_marketdata.paper_execution import slippage_bps


def build_leg_orders(decision: dict, symbols: dict) -> tuple[dict, dict]:
    """Long leg buys on decision['long_venue']; short leg sells on decision['short_venue']; each at leg_notional."""
    n = float(decision["leg_notional"])
    lv, sv = decision["long_venue"], decision["short_venue"]
    long_order = {"leg": "long", "venue": lv, "symbol": symbols[lv], "side": "buy", "notional": n}
    short_order = {"leg": "short", "venue": sv, "symbol": symbols[sv], "side": "sell", "notional": n}
    return long_order, short_order


def _place_one(venues: dict, order: dict, *, dry_run: bool) -> dict:
    """Place one leg; capture any raise as ok=False (report never crash). Attaches the venue mid + leg/venue."""
    try:
        v = venues[order["venue"]]
        mid = v.mid(order["symbol"])
        fill = v.place_market(order["symbol"], order["side"], order["notional"], mid, dry_run=dry_run)
        return {**order, **fill, "mid": mid}
    except Exception as e:  # noqa: BLE001 -- report never crash: a venue failure is a NAKED leg, not a traceback
        return {**order, "ok": False, "placed": False, "error": str(e)}


def place_both(venues: dict, long_order: dict, short_order: dict, *, dry_run: bool) -> tuple[dict, dict]:
    """Place BOTH legs (measure the true cross-venue outcome, incl. a naked window); neither raises out."""
    return _place_one(venues, long_order, dry_run=dry_run), _place_one(venues, short_order, dry_run=dry_run)


def reconcile(long_fill: dict, short_fill: dict, *, tolerance: float) -> dict:
    """Delta-neutral reconciliation: NAKED if a leg failed / was not placed; else imbalance = |long - short|."""
    if not (long_fill.get("ok") and short_fill.get("ok") and long_fill.get("placed") and short_fill.get("placed")):
        return {"status": "NAKED", "imbalance_usd": float("nan"), "long_notional": None, "short_notional": None}
    ln = float(long_fill["filled"]) * float(long_fill["avg_price"])
    sn = float(short_fill["filled"]) * float(short_fill["avg_price"])
    imb = abs(ln - sn)
    return {"status": "OK" if imb <= tolerance else "IMBALANCED", "imbalance_usd": imb,
            "long_notional": ln, "short_notional": sn}


def _leg_friction_bps(open_fill: dict, close_fill: dict, *, taker_fee_bps: float) -> float:
    """Round-trip friction (bps) for one leg: entry + exit slippage vs mid + 2*fee. NaN if either leg not ok."""
    if not (open_fill.get("ok") and close_fill.get("ok") and open_fill.get("placed") and close_fill.get("placed")):
        return float("nan")
    entry = slippage_bps(float(open_fill["avg_price"]), float(open_fill["mid"]), side=open_fill["side"])
    exit_ = slippage_bps(float(close_fill["avg_price"]), float(close_fill["mid"]), side=close_fill["side"])
    return entry + exit_ + 2.0 * taker_fee_bps


def _reverse(order: dict) -> dict:
    return {**order, "side": "sell" if order["side"] == "buy" else "buy"}


def run_probe(venues, decision, symbols, *, tolerance, taker_fee_bps, dry_run) -> dict:
    """Open then close the pair -> reconciliation + per-leg round-trip friction. If the OPEN does not reconcile OK
    (a leg failed = NAKED, or IMBALANCED), HALT: place NO close legs (no auto-unwind, no fresh naked position, per
    the 'place both, reconcile after' posture) and report the open reconcile with NaN friction."""
    lo, so = build_leg_orders(decision, symbols)
    o_long, o_short = place_both(venues, lo, so, dry_run=dry_run)
    rec = reconcile(o_long, o_short, tolerance=tolerance)
    out = {"mode": "probe", "open": {"long": o_long, "short": o_short}, "reconcile": rec}
    if rec["status"] != "OK":
        out["close"] = None
        out["friction_bps"] = {"long": float("nan"), "short": float("nan")}
        out["halted"] = rec["status"]
        return out
    c_long, c_short = place_both(venues, _reverse(lo), _reverse(so), dry_run=dry_run)
    out["close"] = {"long": c_long, "short": c_short}
    out["friction_bps"] = {"long": _leg_friction_bps(o_long, c_long, taker_fee_bps=taker_fee_bps),
                           "short": _leg_friction_bps(o_short, c_short, taker_fee_bps=taker_fee_bps)}
    return out


def run_hold_open(venues, decision, symbols, *, state_path, dry_run) -> dict:
    """Open the pair and persist state for a later hold-close. Refuses if a position is already open."""
    state_path = Path(state_path)
    if state_path.exists():
        raise SystemExit(f"a hold position is already open ({state_path}); close it before opening another")
    lo, so = build_leg_orders(decision, symbols)
    o_long, o_short = place_both(venues, lo, so, dry_run=dry_run)
    rec = reconcile(o_long, o_short, tolerance=float("inf"))     # record open imbalance; hold-close gates on tol
    if not dry_run and rec["status"] != "NAKED":                 # do NOT record a NAKED half-open as a valid hold
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"long_order": lo, "short_order": so,
                                          "open_fills": {"long": o_long, "short": o_short},
                                          "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}))
    return {"mode": "hold-open", "open": {"long": o_long, "short": o_short}, "reconcile": rec}


def run_hold_close(venues, symbols, *, state_path, tolerance, taker_fee_bps, dry_run) -> dict:
    """Read the open-position state, place the reverse, reconcile, and (armed) clear the state. Refuses if none."""
    state_path = Path(state_path)
    if not state_path.exists():
        raise SystemExit(f"no open hold position at {state_path}; nothing to close")
    st = json.loads(state_path.read_text())
    lo, so = st["long_order"], st["short_order"]
    o_long, o_short = st["open_fills"]["long"], st["open_fills"]["short"]
    c_long, c_short = place_both(venues, _reverse(lo), _reverse(so), dry_run=dry_run)
    out = {
        "mode": "hold-close",
        "close": {"long": c_long, "short": c_short},
        "reconcile": reconcile(c_long, c_short, tolerance=tolerance),
        "friction_bps": {"long": _leg_friction_bps(o_long, c_long, taker_fee_bps=taker_fee_bps),
                         "short": _leg_friction_bps(o_short, c_short, taker_fee_bps=taker_fee_bps)},
    }
    if not dry_run:
        state_path.unlink()
    return out
