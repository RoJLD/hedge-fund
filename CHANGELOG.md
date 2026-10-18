# Changelog

All notable changes to **hedge-fund** (proprietary) are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/).
The live delta-neutral cross-venue funding-carry fund. Design/operational rationale lives in
[`docs/decisions.md`](docs/decisions.md); the cross-repo dependency map is in the Quant-lab repo's
`docs/PLATFORM.md`.

## [Unreleased]

### Added
- **Code layer in the operations graph** (`ops/graph/nodes/code.yaml`, `ops/graph/edges/code.yaml`): 11 `CodeRef`
  nodes naming the fund's code (`code:hedge-fund:<path>[::<symbol>]`), linked by `implemented_by` from the two
  harnesses, the deployment, the paper and testnet stages, the testnet limit, two ADRs and the two testnet accounts.
  `hedge_fund.ops_graph check` verifies with `ast` (no import) that each active file and symbol exists, and enforces
  the layer's edge rules. Quant-lab's `code-check --overlay ../hedge-fund/ops/graph` sees them too. No new
  dependency.

## [0.2.0] — 2026-10-17

### Added
- **Operations graph** (`ops/graph/`, `hedge_fund.ops_graph`): the operations layer of the platform graph —
  the cross-venue deployment, its stages (paper, testnet, live pilot), gates, harnesses, accounts (environment
  variable names only), limits, runbook and operational ADRs — in the YAML format of Quant-lab's research graph.
  `python -m hedge_fund.ops_graph check|stages`; Quant-lab ids are declared in `ops/graph/external.yaml`, and
  Quant-lab overlays the store read-only for cross-repo queries. No new dependency.

### Changed
- **`quant-marketdata[live]` pinned to `v0.3.0`** (multi-venue data layer; additive, the fund's imports are
  unchanged). Full suite green on a clean, non-editable install from the tag.

### Fixed
- **Packaging**: the deploy configs (`paper_config.yaml`, `testnet_config.yaml`) are now package data, and the
  CLIs resolve them relative to the package instead of `ROOT/src/...`. A non-editable install previously had no
  config to load (`cross_venue_testnet` failed with FileNotFoundError); editable installs hid it.

## [0.1.1] — 2026-08-02

### Fixed
- **Stale dependency pin**: bumped `quant-marketdata[live]` from `v0.1.0` → `v0.2.0`. The fund's cross-venue
  paper/testnet code imports `quant_marketdata.funding_diff` (the funding-data layer added in quant-marketdata
  v0.2.0), so a clean install from the old pin would `ImportError`; the local suite stayed green only because
  the installed copy was already 0.2.0 (editable). Caught by the cross-repo pin-coherence guard.

## [0.1.0] — 2026-08-02

Initial release. The live cross-venue funding-carry fund, graduated from the Quant-lab research program to its
own repository (platform "Move 1"), depending only on the published `quant-marketdata[live]`.

### Added
- **Decision engine + paper harness** (`deploy/cross_venue`): `engine.decide` (the daily delta-neutral target),
  the read-only paper snapshot (advisory + log + debounced tripwire alerts), and the testnet orchestrator.
- **Execution adapters** (`execution/`): the `ExecutionVenue` Protocol + a `FakeTestnetVenue` double + Binance
  and Hyperliquid testnet adapters (testnet-only by construction, dry-run default, `--arm`-gated).
- **Two CLIs**: `cross_venue_paper` (read-only daily harness) and `cross_venue_testnet` (dry-run/`--arm`).
- Fund boilerplate: config/paths loaders, `alerting.evaluate_alert`, LICENSE (proprietary), the T7 cutover
  runbook (`docs/runbooks/cutover-from-quant-lab.md`).

[0.2.0]: https://github.com/RoJLD/hedge-fund/releases/tag/v0.2.0
[0.1.1]: https://github.com/RoJLD/hedge-fund/releases/tag/v0.1.1
[0.1.0]: https://github.com/RoJLD/hedge-fund/releases/tag/v0.1.0
