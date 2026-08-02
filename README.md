# hedge-fund

**Live delta-neutral cross-venue funding-carry deployment** — the operational fund extracted from the
Quant-lab research monorepo (topology Move 1), so its lifecycle (daily cron, secrets, uptime) is isolated
from research churn. **Proprietary — not open source.**

The edge (`E-cross-venue-funding-diff`): long the low-funding venue perp / short the high-funding venue perp,
delta-neutral, sized to a friction/capacity envelope. Validated in Quant-lab across four realism layers
(exp082–085) and staged: record → **paper (live)** → **testnet (built)** → tiny live pilot (gated).

## What's here

- `deploy/cross_venue/` — the decision engine (`engine.decide`), the read-only **paper harness**, and the
  **testnet execution adapter** (place-both / reconcile, HALT-on-NAKED, report-never-crash).
- `execution/` — venue adapters: Binance USDⓈ-M futures testnet + Hyperliquid testnet (testnet-only by
  construction; dry-run default; `--arm`-gated).
- `monitor/` — fund-ops monitoring (freshness) + the persistence-gated alert debounce.
- `cli/` — the runners: `cross_venue_paper` (daily L3), `cross_venue_testnet`, `carry_monitor`, etc.

## Dependencies

Market-data / execution-simulation primitives come from the published **`quant-marketdata`** package
(book-walking fills, market impact, funding-carry cost, live quotes). This repo carries only its own thin
boilerplate (`config`, `paths`, `alerting.evaluate_alert`).

## Hard safety boundary

**Secrets are env-only, never committed.** The deployment never auto-arms: placing/arming testnet or live
orders is a deliberate, credentialed, human step (`--arm`, gated). Testnet-only by construction until the
Stage-2→3 gate and a separate live-pilot decision.

*Not financial advice.*
