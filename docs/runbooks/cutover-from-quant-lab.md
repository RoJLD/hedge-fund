# Runbook — Move 1 cutover: hedge-fund ← Quant-lab (T7)

> **Status: ready, ORDER-SENSITIVE.** The fund repo is published + standalone-green (v0.1.0). This is the final
> step of Move 1: migrate the live daily cron + its state from Quant-lab to this repo, then remove the fund's
> code from Quant-lab. **Do the steps in order** — removing the fund from Quant-lab BEFORE the cron flips would
> break the live L3 paper harness. The cron flip is Robin's credentialed step; the assistant never flips the
> live task nor arms orders.

## Current safe state (before cutover)

The fund exists in BOTH repos: Quant-lab still has the originals (its daily cron runs
`quant_lab.cli.cross_venue_paper` = L3, unchanged and working), and `hedge-fund` has the standalone copy. This
duplication is intentional and non-breaking until the flip.

## Step 1 — Install the fund + set the shared funding cache (Robin, on the cron host)

```bash
pip install -e "C:/Users/rdenis/VScode/hedge-fund[deploy]"        # or: pip install "git+https://github.com/RoJLD/hedge-fund.git@v0.1.0[deploy]"
setx QUANT_FUNDING_CACHE "C:/Users/rdenis/VScode/Quant-lab/data/raw"   # point the fund at the SHARED 2019+ funding cache
```
The `QUANT_FUNDING_CACHE` env var is load-bearing: it makes `hedge_fund`'s `cross_venue_diff` read the same
2019+ Binance funding cache the research book uses (the exp081 cache-safety lesson). Without it the fund
re-fetches into its own cache (correct, but not shared).

## Step 2 — Migrate the accumulating paper-gate state (assistant can do; a file copy, not arming)

```bash
mkdir -p C:/Users/rdenis/VScode/hedge-fund/results/carry_monitor
cp C:/Users/rdenis/VScode/Quant-lab/results/carry_monitor/cross_venue_paper_log.parquet \
   C:/Users/rdenis/VScode/hedge-fund/results/carry_monitor/          # do this AT the flip so no runs are lost
```
`results/` is gitignored (operational state, not source). Do the copy at the flip moment so the ~4-week gate
record carries over intact.

## Step 3 — Flip the daily cron L3 (Robin's credentialed step)

- Edit Quant-lab `scripts/monitoring_cycle.ps1`: remove the L3 step (`quant_lab.cli.cross_venue_paper`).
- Point the Windows Scheduled Task (or a fund-repo cron script) at `python -m hedge_fund.cli.cross_venue_paper`
  from the fund repo. Confirm ONE manual run: `python -m hedge_fund.cli.cross_venue_paper` (read-only, prints
  the advisory + appends to the migrated log).
- The assistant prepares the scripts but does NOT flip the live task.

## Step 4 — Remove the fund from Quant-lab (assistant, AFTER the flip is confirmed)

Remove (with their tests) — these are the fund, now live in `hedge-fund`:
- `src/quant_lab/deploy/cross_venue/` (+ `deploy/` if empty) and `tests/test_cross_venue_{engine,paper,testnet}.py`, `tests/test_cross_venue_testnet_smoke.py`
- `src/quant_lab/cli/cross_venue_paper.py`, `cross_venue_testnet.py` and `tests/test_cross_venue_{paper,testnet}_cli.py`
- `src/quant_lab/execution/{venue,binance_testnet,hyperliquid_testnet}.py` and `tests/test_{execution_venue,binance_testnet_venue,hyperliquid_testnet_venue}.py`
- the cross_venue configs; the L3 wiring already removed in Step 3.

KEEP in Quant-lab (research/legacy):
- `src/quant_lab/execution/testnet.py` + `tests/test_testnet_execution.py` — the **legacy `testnet_execution` CLI**
  (demoted absolute carry) still imports it. ⚠️ This is the shared-with-legacy edge; do NOT remove execution/testnet.py.
- `cli/{carry_monitor,paper_execution,testnet_execution,freshness_check,reconfirm,reconfirm_alerts}.py`,
  `monitor/*` (the market-data + funding shims, `reconfirm`, `alerting`, `freshness`), all `experiments/`.

Then: update `tests/test_module_layering.py` (drop `deploy` + the removed execution modules from the fund cluster;
`execution` stays but reduced to `testnet`). Run the Quant-lab **full suite** green. Update the topology spec +
roadmap: **Move 1 DONE**.

## Verification

- Fund repo: `pytest` green standalone; one manual `cross_venue_paper` run appends to the migrated log.
- Quant-lab: full suite green after removal; the daily cron runs L0/L1/L2 (research) with no L3 (moved).
- The paper-gate record is continuous across the migration (Step 2).
