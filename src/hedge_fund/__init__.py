"""hedge_fund -- live delta-neutral cross-venue funding-carry deployment (proprietary).

Extracted from the Quant-lab research monorepo (topology Move 1). Market-data / execution-simulation
primitives come from the published ``quant-marketdata`` package; this repo carries the decision engine,
the testnet execution adapters, fund-ops monitoring, the runners, and thin boilerplate (config/paths/
alerting). Testnet-only by construction; the deployment never auto-arms.
"""

__version__ = "0.1.0"
