"""Cross-venue carry paper harness runner (deploy Stage 1) -- READ-ONLY, places NOTHING, needs no keys.

One daily snapshot: live Δf + books -> the decision engine -> shadow-book friction + tripwires -> an advisory
(stdout, the CURRENT state every run) + a log row per asset (results/carry_monitor/cross_venue_paper_log.parquet).
notes/alerts.md is DEBOUNCED exactly like the L2 reconfirm monitor: a tripwire surfaces only after it PERSISTS
(reuses hedge_fund.alerting.evaluate_alert over the accumulated log), so a one-run blip -- or a single transient
fetch error -- never spams the ~4-week gate window. Exit code: 2 any persistent FAIL, 1 any persistent WARN, else 0.

Usage::  python -m hedge_fund.cli.cross_venue_paper            # live snapshot (read-only)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from hedge_fund.alerting import evaluate_alert
from hedge_fund.deploy.cross_venue.paper import paper_snapshot
from hedge_fund.paths import ROOT

_CONFIG = ROOT / "src" / "hedge_fund" / "deploy" / "cross_venue" / "paper_config.yaml"
_LOG = ROOT / "results" / "carry_monitor" / "cross_venue_paper_log.parquet"
_ALERTS = ROOT / "notes" / "alerts.md"


def render_advisory(snapshot: dict) -> list[str]:
    """Human advisory (stdout, the CURRENT run's state every time -- NOT debounced): per asset the delta-neutral
    legs, sizes, expected carry, live friction, and tripwire; an unreadable asset shows a labeled data error."""
    lines = ["cross-venue carry paper advisory (READ-ONLY -- places nothing):"]
    for a, s in snapshot.items():
        if s["tripwire"] == "ERROR":
            lines.append(f"  {a}: DATA/NETWORK error -- could not check today ({s['error']}); NOT a strategy signal")
            continue
        lines.append(
            f"  {a}: hold pos={s['position']:+.0f} | long {s['long_venue']} / short {s['short_venue']} "
            f"@ {s['leg_notional']:.0f} USD/leg | diff={s['annualized_diff']:+.4f} "
            f"carry/day={s['expected_daily_carry']:+.2e} | roundtrip={s['roundtrip_bps']:.1f}bps | "
            f"tripwire={s['tripwire']} (recency_ok={s['recency_ok']} friction_ok={s['friction_ok']})"
        )
    return lines


def append_log(snapshot: dict, path: Path) -> None:
    """Append one row per asset to the parquet log (create on first run, append after)."""
    rows = [{"asset": a, **{k: v for k, v in s.items()}} for a, s in snapshot.items()]
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
    df.to_parquet(path)


def evaluate_paper_alerts(log_df: pd.DataFrame, *, alert_persistence: int = 2, warn_persistence: int = 3) -> list[dict]:
    """Persistence-gated per-asset alerts over the paper log -- mirrors the L2 reconfirm monitor so L3 debounces the
    same way: only a PERSISTENT tripwire surfaces, never a one-run blip. FAIL = tripwire FAIL for `alert_persistence`
    consecutive runs; WARN = WARN-or-FAIL for `warn_persistence` runs (ERROR is EXCLUDED from this verdict gate -- a
    could-not-check is not a strategy verdict); a persistent ERROR (a real data outage) escalates to WARN. Silent
    (no record) when healthy or not-yet-persistent. One row per asset per run -> one observation == one run."""
    records: list[dict] = []
    for asset, g in log_df.groupby("asset"):
        g = g.sort_values("asof")
        statuses = g["tripwire"].astype(str)
        verdicts = statuses[statuses != "ERROR"]                     # exclude could-not-check from the verdict gate
        fail = evaluate_alert(verdicts, alert_statuses={"FAIL"}, persistence=alert_persistence)
        warn = evaluate_alert(verdicts, alert_statuses={"WARN", "FAIL"}, persistence=warn_persistence)
        err = evaluate_alert(statuses, alert_statuses={"ERROR"}, persistence=warn_persistence)
        if fail["fired"]:
            sev, ev = "FAIL", fail
        elif warn["fired"]:
            sev, ev = "WARN", warn
        elif err["fired"]:
            sev, ev = "WARN", err                                    # a persistent data outage -> WARN (like STALE)
        else:
            continue
        records.append({"asset": str(asset), "severity": sev, "consecutive": ev["consecutive"],
                        "latest_status": str(statuses.iloc[-1]), "latest_date": g["asof"].iloc[-1]})
    return records


def format_paper_alert_lines(records: list[dict], *, now: pd.Timestamp) -> list[str]:
    """Render fired (persistent) records as notes/alerts.md lines in the existing OK/WARN/FAIL grammar (the `now`
    parameter mirrors the L2 formatter's signature; the dated stamp comes from latest_date)."""
    lines: list[str] = []
    for r in records:
        latest = pd.Timestamp(r["latest_date"]).date()
        lines.append(
            f"{r['severity']}  cross_venue_paper:{r['asset']}  tripwire {r['latest_status']} "
            f"{r['consecutive']} consecutive runs (latest {latest})"
        )
    return lines


def _exit_code(records: list[dict]) -> int:
    """Debounced cycle signal: 2 if any persistent FAIL, 1 if any persistent WARN, else 0. A one-run blip (not yet
    persistent) yields no record -> 0, so a transient dip never flips the cycle."""
    severities = {r["severity"] for r in records}
    if "FAIL" in severities:
        return 2
    if "WARN" in severities:
        return 1
    return 0


def main() -> None:
    cfg = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    snapshot = paper_snapshot(
        cfg["assets"], notional=float(cfg["notional"]), k=int(cfg["k"]),
        taker_fee_bps=float(cfg["taker_fee_bps"]), friction_envelope_bps=float(cfg["friction_envelope_bps"]),
        recency_window=int(cfg["recency_window"]), recency_threshold=float(cfg["recency_threshold"]),
        leverage=float(cfg["leverage"]), start=cfg["start"], use_cache=False)
    print("\n".join(render_advisory(snapshot)))
    append_log(snapshot, _LOG)                                       # the current run's rows are now in the log
    now = pd.Timestamp.now("UTC")
    records = evaluate_paper_alerts(pd.read_parquet(_LOG),
                                    alert_persistence=int(cfg.get("alert_persistence", 2)),
                                    warn_persistence=int(cfg.get("warn_persistence", 3)))
    if records:
        lines = format_paper_alert_lines(records, now=now)
        block = f"\n## {now.date()} — cross-venue paper monitor\n" + "\n".join(lines) + "\n"
        with _ALERTS.open("a", encoding="utf-8") as fh:
            fh.write(block)
        for ln in lines:
            print(f"[cross_venue_paper] {ln}")
    else:
        print("[cross_venue_paper] clean -- no persistent tripwire")
    sys.exit(_exit_code(records))


if __name__ == "__main__":
    main()
