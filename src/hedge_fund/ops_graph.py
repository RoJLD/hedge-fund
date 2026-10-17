"""The fund's operations graph (ops/graph): load, validate, list stages.

Same YAML format as Quant-lab's research graph, validated here with PyYAML only (the fund depends on no
research package). Edges may target Quant-lab nodes declared in ``ops/graph/external.yaml``; Quant-lab can overlay
this store on its own graph (``--overlay``) to query impact and decisions across both.

Usage::

    python -m hedge_fund.ops_graph check      # schema, statuses, unique ids, edge endpoints, anchors
    python -m hedge_fund.ops_graph stages     # deployments and their stages, gates and blockers
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "ops" / "graph"
SECRET_HINTS = ("secret", "private_key", "api_key", "password", "mnemonic")


def _load_list(path: Path) -> list:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list")
    return data


@dataclass
class OpsGraph:
    nodes: Dict[str, dict]
    edges: List[dict]
    external: Dict[str, str]
    problems: List[str] = field(default_factory=list)


def load(store: Path = STORE, repo_root: Path = ROOT) -> OpsGraph:
    schema = yaml.safe_load((store / "schema.yaml").read_text(encoding="utf-8"))
    node_types, edge_types = set(schema["node_types"]), set(schema["edge_types"])
    statuses = set(schema["statuses"])
    by_type = {t: set(v) for t, v in (schema.get("status_by_type") or {}).items()}
    problems: List[str] = []
    nodes: Dict[str, dict] = {}
    for f in sorted((store / "nodes").glob("*.yaml")):
        for n in _load_list(f):
            nid = n.get("id")
            if nid in nodes:
                problems.append(f"duplicate node id: {nid}")
                continue
            if n.get("type") not in node_types:
                problems.append(f"{nid}: unknown type {n.get('type')!r}")
            status = n.get("status")
            if status not in statuses or status not in by_type.get(n.get("type"), statuses):
                problems.append(f"{nid}: status {status!r} not allowed for type {n.get('type')!r}")
            anchor = n.get("anchor")
            if anchor and not (repo_root / anchor.split("#", 1)[0]).exists():
                problems.append(f"{nid}: anchor file missing: {anchor}")
            props = n.get("props") or {}
            for key, value in props.items():
                if key != "env" and any(h in key.lower() for h in SECRET_HINTS):
                    problems.append(f"{nid}: property {key!r} looks like a secret; store env var names in `env` only")
                if key == "env" and not all(isinstance(v, str) and v.isupper() for v in value):
                    problems.append(f"{nid}: `env` must list environment variable NAMES")
            nodes[nid] = n
    external = {e["id"]: e.get("repo", "?") for e in _load_list(store / "external.yaml")}
    for clash in sorted(set(external) & set(nodes)):
        problems.append(f"{clash}: declared both locally and as external")
    edges: List[dict] = []
    seen_pairs = set()
    for f in sorted((store / "edges").glob("*.yaml")):
        for e in _load_list(f):
            s, d, t = e.get("from"), e.get("to"), e.get("type")
            if t not in edge_types:
                problems.append(f"edge {s}->{d}: unknown type {t!r}")
            for end in (s, d):
                if end not in nodes and end not in external:
                    problems.append(f"edge {s}->{d}: unknown node {end!r} (define it or declare it in external.yaml)")
            if (s, d) in seen_pairs:
                problems.append(f"edge {s}->{d}: several edges on one node pair (graphs keep one)")
            seen_pairs.add((s, d))
            edges.append(e)
    return OpsGraph(nodes, edges, external, problems)


def stages(graph: OpsGraph) -> List[str]:
    """One line per deployment stage: status, gate and its state, external blocker if any."""
    out = []
    parts = [e for e in graph.edges if e["type"] == "part_of"]
    gates = {e["from"]: e["to"] for e in graph.edges if e["type"] == "gated_by"}
    for dep in sorted(n for n, v in graph.nodes.items() if v["type"] == "Deployment"):
        out.append(f"{dep} [{graph.nodes[dep]['status']}] {graph.nodes[dep].get('title', '')}")
        for e in sorted(parts, key=lambda e: e["from"]):
            if e["to"] != dep:
                continue
            st = graph.nodes[e["from"]]
            line = f"  {e['from']} [{st['status']}]"
            gate = gates.get(e["from"])
            if gate:
                line += f"  gate {gate} [{graph.nodes[gate]['status']}]"
            blocker = (st.get("props") or {}).get("external_blocker")
            if blocker:
                line += f"  blocked by: {blocker}"
            out.append(line)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hedge_fund.ops_graph")
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("cmd", choices=["check", "stages"])
    args = parser.parse_args(argv)
    graph = load(args.store, args.store.resolve().parents[1])
    if args.cmd == "stages":
        print("\n".join(stages(graph)))
        return 0
    for p in graph.problems:
        print(p, file=sys.stderr)
    print(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges, {len(graph.external)} external refs: "
          + ("OK" if not graph.problems else f"{len(graph.problems)} problem(s)"))
    return 1 if graph.problems else 0


if __name__ == "__main__":
    sys.exit(main())
