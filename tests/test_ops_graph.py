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


# -- code layer: operations nodes -> this repo's code (implemented_by) ----------------------------

FAKE_MODULE = '''from hedge_fund.config import load_config as reexported

CAP: float = 100.0

try:
    import fast
except ImportError:
    def fallback():
        return None


class Venue:
    name = "fake"

    def place(self, order):
        def helper():
            return order
        return helper()


def decide(diff):
    return diff
'''


def _code_store(tmp_path: Path, nodes: str, edges: str) -> tuple[Path, Path]:
    """A copy of the real store whose code layer is replaced, and a fake repo root holding src/hedge_fund/fake.py."""
    store = _copy(tmp_path)
    (store / "nodes" / "code.yaml").write_text(nodes, encoding="utf-8")
    (store / "edges" / "code.yaml").write_text(edges, encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "src" / "hedge_fund").mkdir(parents=True)
    (repo / "src" / "hedge_fund" / "fake.py").write_text(FAKE_MODULE, encoding="utf-8")
    (repo / "src" / "hedge_fund" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "runbook.md").write_text("# r\n", encoding="utf-8")
    for anchor in ("src/hedge_fund/deploy/cross_venue/paper_config.yaml",
                   "src/hedge_fund/deploy/cross_venue/testnet_config.yaml",
                   "docs/runbooks/cutover-from-quant-lab.md", "docs/decisions.md"):
        (repo / anchor).parent.mkdir(parents=True, exist_ok=True)
        (repo / anchor).write_text("x\n", encoding="utf-8")
    return store, repo


def _ref(cid: str, status: str = "active") -> str:
    return f"- {{id: '{cid}', type: CodeRef, status: {status}, title: t}}\n"


def _link(src: str, cid: str, etype: str = "implemented_by") -> str:
    return f"- {{from: {src}, to: '{cid}', type: {etype}}}\n"


def test_real_store_links_harnesses_and_venues_to_code():
    graph = load(STORE, ROOT)
    links = {(e["from"], e["to"]) for e in graph.edges if e["type"] == "implemented_by"}
    assert ("harness-paper-cli", "code:hedge-fund:hedge_fund/cli/cross_venue_paper.py::main") in links
    assert ("harness-testnet-cli", "code:hedge-fund:hedge_fund/cli/cross_venue_testnet.py::main") in links
    assert ("acct-hl-testnet",
            "code:hedge-fund:hedge_fund/execution/hyperliquid_testnet.py::HyperliquidTestnetVenue") in links
    assert graph.problems == []


def test_code_refs_resolve_with_ast(tmp_path):
    good = ["code:hedge-fund:hedge_fund/fake.py::Venue", "code:hedge-fund:hedge_fund/fake.py::Venue.place",
            "code:hedge-fund:hedge_fund/fake.py::Venue.name", "code:hedge-fund:hedge_fund/fake.py::decide",
            "code:hedge-fund:hedge_fund/fake.py::CAP", "code:hedge-fund:hedge_fund/fake.py::fallback",
            "code:hedge-fund:hedge_fund/fake.py", "code:hedge-fund:docs/runbook.md"]
    retired = "code:hedge-fund:hedge_fund/gone.py::Old"
    store, repo = _code_store(tmp_path, "".join(_ref(c) for c in good) + _ref(retired, "retired"),
                              "".join(_link("stage-paper", c) for c in good + [retired]))
    assert load(store, repo).problems == []  # the retired one is not looked for


def test_code_refs_report_missing_file_symbol_and_parse_errors(tmp_path):
    refs = {
        "code:hedge-fund:hedge_fund/gone.py::decide": "file missing: neither src/hedge_fund/gone.py",
        "code:hedge-fund:hedge_fund/Fake.py::decide": "file missing",  # case must match exactly
        "code:hedge-fund:hedge_fund/fake.py::renamed": "renamed is not defined in hedge_fund/fake.py",
        "code:hedge-fund:hedge_fund/fake.py::reexported": "reexported is not defined",  # an import is not a definition
        "code:hedge-fund:hedge_fund/fake.py::Venue.place.helper": "is not defined",  # no look into function bodies
        "code:hedge-fund:hedge_fund/broken.py::oops": "cannot parse hedge_fund/broken.py",
        "code:quant-marketdata:quant_marketdata/funding_diff.py::cross_venue_diff": "names this repo's code",
        "code:hedge-fund:../escape.py": "bad path",
        "code:hedge-fund:ops/graph/schema.yaml::key": "bad symbol",
    }
    sources = ["stage-paper", "stage-testnet", "stage-live-pilot", "harness-paper-cli", "harness-testnet-cli",
               "harness-monitoring-cycle", "acct-binance-testnet", "acct-hl-testnet", "lim-paper"]
    store, repo = _code_store(tmp_path, "".join(_ref(c) for c in refs),
                              "".join(_link(s, c) for s, c in zip(sources, refs, strict=True)))
    problems = load(store, repo).problems
    for cid, why in refs.items():
        assert any(p.startswith(f"{cid}: ") and why in p for p in problems), (cid, problems)


def test_code_layer_edge_rules(tmp_path):
    ref = "code:hedge-fund:hedge_fund/fake.py::decide"
    nodes = _ref(ref) + _ref("code:hedge-fund:hedge_fund/fake.py::CAP") \
        + "- {id: 'code:hedge-fund:x.py', type: Limit, status: active, title: reserved prefix}\n"
    edges = (_link("dep-cross-venue-carry", ref)
             + "- {from: stage-paper, to: lim-paper, type: implemented_by}\n"
             + f"- {{from: '{ref}', to: stage-paper, type: depends_on}}\n"
             + _link("stage-testnet", ref, "depends_on"))
    store, repo = _code_store(tmp_path, nodes, edges)
    problems = "\n".join(load(store, repo).problems)
    assert "edge stage-paper->lim-paper: implemented_by must point at a CodeRef" in problems
    assert f"edge {ref}->stage-paper: a CodeRef has no outgoing edge" in problems
    assert f"edge stage-testnet->{ref}: only implemented_by may point at a CodeRef, got 'depends_on'" in problems
    assert "code:hedge-fund:hedge_fund/fake.py::CAP: CodeRef with no implemented_by" in problems
    assert "code:hedge-fund:x.py: ids under 'code:' are reserved" in problems
