"""Resolve fund-repo paths from any working directory.

ROOT is this repo's root (src/hedge_fund/paths.py -> parents[2]); the fund's operational state
(results/, configs) lives under it -- correctly pointing at the fund repo after the extraction.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
CONFIGS = ROOT / "configs"
DATA = ROOT / "data"
