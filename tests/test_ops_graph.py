"""Operations graph (ops/graph): the real store validates, and the validator catches what it must."""

from __future__ import annotations

import shutil
from pathlib import Path

from hedge_fund.ops_graph import load, main, stages

# The store lives in the repo, not in the installed package: resolve it from this file.
ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "ops" / "graph"


def _copy(tmp_path: Path) -> Path:
    dst = tmp_path / "graph"
    shutil.copytree(STORE, dst)
    return dst


def test_real_store_is_valid():
    graph = load(STORE, ROOT)
    assert graph.problems == []
    assert graph.nodes["stage-testnet"]["status"] == "blocked"
    assert "E-cross-venue-funding-diff" in graph.external


def test_stages_lists_gates_and_blockers():
    lines = stages(load(STORE, ROOT))
    assert lines[0].startswith("dep-cross-venue-carry [active]")
    testnet = next(line for line in lines if "stage-testnet" in line)
    assert "gate gate-paper-to-testnet [pending]" in testnet and "blocked by:" in testnet


def test_unknown_endpoint_must_be_declared_external(tmp_path):
    store = _copy(tmp_path)
    (store / "edges" / "extra.yaml").write_text(
        "- {from: stage-paper, to: venue-lighter, type: runs_on}\n", encoding="utf-8")
    problems = load(store, ROOT).problems
    assert any("unknown node 'venue-lighter'" in p for p in problems)


def test_status_and_secret_guards(tmp_path):
    store = _copy(tmp_path)
    (store / "nodes" / "extra.yaml").write_text(
        "- {id: gate-x, type: Gate, status: active, title: x}\n"
        "- {id: acct-x, type: Account, status: planned, title: x, props: {api_key: abc}}\n"
        "- {id: acct-y, type: Account, status: planned, title: y, props: {env: [not_a_name]}}\n",
        encoding="utf-8")
    problems = load(store, ROOT).problems
    assert any("gate-x: status 'active' not allowed" in p for p in problems)
    assert any("acct-x: property 'api_key' looks like a secret" in p for p in problems)
    assert any("acct-y: `env` must list environment variable NAMES" in p for p in problems)


def test_duplicate_pairs_and_ids(tmp_path):
    store = _copy(tmp_path)
    (store / "nodes" / "extra.yaml").write_text("- {id: lim-paper, type: Limit, status: active, title: dup}\n",
                                                encoding="utf-8")
    (store / "edges" / "extra.yaml").write_text("- {from: stage-paper, to: lim-paper, type: decided_by}\n",
                                                encoding="utf-8")
    problems = load(store, ROOT).problems
    assert "duplicate node id: lim-paper" in problems
    assert any("several edges on one node pair" in p for p in problems)


def test_cli_exit_codes(tmp_path, capsys):
    assert main(["--store", str(STORE), "check"]) == 0
    store = _copy(tmp_path)
    (store / "edges" / "extra.yaml").write_text("- {from: a, to: b, type: nope}\n", encoding="utf-8")
    assert main(["--store", str(store), "check"]) == 1
    assert "unknown type 'nope'" in capsys.readouterr().err
