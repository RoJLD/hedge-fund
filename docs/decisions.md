# hedge-fund — decision log (ADR-lite)

Operational & safety decisions for the fund, append-only. Each entry: **Decision · Context · Why · Revisit if**.
This is the fund's local record; the platform-wide topology rationale lives in the Quant-lab repo's specs +
`docs/PLATFORM.md`. Not a research log (no experiments/hypotheses here — see Quant-lab for those).

---

## 2026-08-02 — The fund is proprietary and depends ONLY on quant-marketdata[live]

**Decision.** `hedge-fund` ships under an all-rights-reserved LICENSE and declares exactly one platform
dependency: `quant-marketdata[live]`. It does **not** depend on `honest-inference` / `honest-backtest`.
**Context.** Graduated from Quant-lab (platform "Move 1"). The honest-* family is research/inference machinery;
the fund is the operational tip that only needs shared market + funding data.
**Why.** Keeps the proprietary surface minimal and the dependency graph a clean tree (verticals → shared data
only, never vertical → research). A leaked/optional research dep would blur the fund⟂research seam.
**Revisit if.** The fund ever needs an inference primitive at runtime (unlikely — inference belongs to the
research pre-deployment, not to live operation).

## 2026-08-02 — Testnet-only by construction; dry-run default; `--arm`-gated

**Decision.** Execution adapters refuse any non-testnet endpoint (`assert_testnet` allow-list that RAISES),
place nothing without `--arm`, use L=1 + a tiny notional + a hard per-venue cap, and read keys from env only.
**Context.** Staged deploy record → paper → **testnet** → tiny live pilot; the testnet stage validates real
fills without real capital.
**Why.** Make an accidental live/oversized order structurally impossible, not merely discouraged. The default
path (no `--arm`) is a pure dry-run that needs no keys.
**Revisit if.** A mainnet pilot is authorized — that is a NEW, separately-gated code path + ADR, never a flag
flip on this one.

## 2026-08-02 — Place-both-then-reconcile, HALT-on-NAKED (no auto-unwind)

**Decision.** The orchestrator places both legs near-simultaneously, then reconciles: both filled &
delta-neutral within tol → OK; one leg missing → **NAKED → HALT** (no auto-flatten); imbalanced → flagged.
Reports never crash (a per-venue failure is captured, not raised).
**Context.** Two-venue delta-neutral carry; a half-filled state is the dangerous one.
**Why.** Auto-unwinding a NAKED leg can churn into a worse position and fight the operator; halting surfaces it
for a human. "Report-never-crash" keeps the daily harness alive through transient venue errors.
**Revisit if.** A supervised auto-hedge process with its own risk limits is built (would need its own ADR).

## 2026-08-02 — Shared 2019+ funding cache via `QUANT_FUNDING_CACHE`

**Decision.** The fund reads funding through `quant-marketdata`'s call-time cache resolution, pointed at the
research lab's 2019+ cache via the `QUANT_FUNDING_CACHE` env var (set at cutover).
**Why.** The deployed carry book needs 2019+ history; sharing the one cache avoids a truncating re-fetch (the
exp081 scale-artifact lesson) and keeps research and the fund on identical funding inputs.
**Revisit if.** The fund runs on a host without the research cache — then it re-fetches into its own cache
(correct, just not shared).

## 2026-08-02 — The daily paper harness (L3) runs from this repo; arming stays Robin's

**Decision.** The Stage-1 paper harness (`cross_venue_paper`) graduated to this repo and is what the daily
Scheduled Task runs (cutover runbook `docs/runbooks/cutover-from-quant-lab.md`). Any credentialed step — the
cron flip, provisioning keys/wallets, funding, arming real (even testnet) orders — is **Robin's**, never the
assistant's.
**Why.** The paper harness is read-only (no keys/orders), safe to automate; everything that touches funds or
live/testnet order placement is a human-authorized boundary the AI does not cross.
**Revisit if.** Never for the AI-boundary half; the cron/arming half advances on Robin's calendar + operability
of Hyperliquid.

## 2026-10-17 — The operations layer of the platform graph lives here, in YAML, without research code

**Decision.** The fund's operations (deployments, stages, gates, harnesses, accounts, limits, runbooks,
operational ADRs) are a graph store in `ops/graph/`, in the YAML format of Quant-lab's research graph, validated
by `hedge_fund.ops_graph` with PyYAML only. Edges to Quant-lab nodes (the research edge, venues, datasets) point
to ids declared in `ops/graph/external.yaml`. Quant-lab overlays this store read-only (`--overlay`) for
cross-repo queries; this repo never imports Quant-lab.
**Context.** Robin asked for every layer of the platform graph; the operations layer was kept out of Quant-lab
on purpose (fund ⟂ research seam).
**Why.** The fund keeps its single platform dependency (`quant-marketdata[live]`) and its proprietary surface,
while impact questions ("what breaks the paper stage if Binance funding data is wrong?") become answerable
across both repos. Accounts hold environment variable names only, and the validator rejects secret-looking
properties.
**Revisit if.** The overlay needs write access from Quant-lab, or the fund needs graph queries at runtime
(it should not: operations read configs, the graph documents them).

