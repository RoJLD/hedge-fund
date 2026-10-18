"""The fund's operations graph (ops/graph): load, validate, list stages.

Same YAML format as Quant-lab's research graph, validated here with PyYAML only (the fund depends on no
research package). Edges may target Quant-lab nodes declared in ``ops/graph/external.yaml``; Quant-lab can overlay
this store on its own graph (``--overlay``) to query impact and decisions across both.

Code layer: ``CodeRef`` nodes (``code:hedge-fund:<path>[::<symbol>]``, ``<path>`` relative to ``src/`` when the file
is there) name this repo's code, and operations nodes point at them with ``implemented_by``. ``check`` reads each
active one with :mod:`ast` (no import) and fails when its file or symbol is gone. Same rules as Quant-lab's
``quant_lab.research_graph.code_layer``, re-implemented here because the fund never imports research code.

Usage::

    python -m hedge_fund.ops_graph check      # schema, statuses, unique ids, edge endpoints, anchors, code links
    python -m hedge_fund.ops_graph stages     # deployments and their stages, gates and blockers
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "ops" / "graph"
SECRET_HINTS = ("secret", "private_key", "api_key", "password", "mnemonic")
CODE_TYPE = "CodeRef"
CODE_PREFIX = "code:hedge-fund:"  # this repo's code only: research and data code is Quant-lab's to name
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")


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
    problems += code_problems(nodes, edges, repo_root)
    return OpsGraph(nodes, edges, external, problems)


def _definitions(body: list):
    """(name, node) for the definitions of a module or class body, looking into if/try blocks."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield stmt.name, stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                for el in target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]:
                    if isinstance(el, ast.Name):
                        yield el.id, stmt
        elif isinstance(stmt, ast.If):
            yield from _definitions(stmt.body + stmt.orelse)
        elif type(stmt).__name__ in ("Try", "TryStar"):
            handlers = [s for h in stmt.handlers for s in h.body]
            yield from _definitions(stmt.body + handlers + stmt.orelse + stmt.finalbody)


def _defines(tree: ast.Module, symbol: str) -> bool:
    """Whether ``symbol`` (``name`` or ``Class.attr``) is defined in the module; imports do not count."""
    body = tree.body
    for part in symbol.split("."):
        node = next((n for name, n in _definitions(body) if name == part), None)
        if node is None:
            return False
        body = node.body if isinstance(node, ast.ClassDef) else []
    return True


def _code_file(repo_root: Path, path: str) -> Path | None:
    """``src/<path>`` or ``<path>`` in this repo, matching case exactly (Windows would match any case)."""
    for parts in (["src", *path.split("/")], path.split("/")):
        cur = repo_root
        for part in parts:
            try:
                if part not in os.listdir(cur):
                    break
            except OSError:
                break
            cur = cur / part
        else:
            if cur.is_file():
                return cur
    return None


def _code_ref_problem(nid: str, node: dict, repo_root: Path) -> str | None:
    if not nid.startswith(CODE_PREFIX):
        return f"a CodeRef here names this repo's code: {CODE_PREFIX}<path>[::<symbol>]"
    path, sep, symbol = nid[len(CODE_PREFIX):].partition("::")
    if (not path or "\\" in path or ":" in path or path.startswith("/")
            or any(p in {"", ".", ".."} for p in path.split("/"))):
        return f"bad path {path!r} (relative POSIX path, no '.' or '..' segment)"
    if sep and (not _SYMBOL.fullmatch(symbol) or not path.endswith(".py")):
        return f"bad symbol {symbol!r} (identifiers joined by dots, in a .py file)"
    if node.get("status") != "active":
        return None
    target = _code_file(repo_root, path)
    if target is None:
        return f"file missing: neither src/{path} nor {path}"
    if not sep:
        return None
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        return f"cannot parse {path}: {exc}"
    return None if _defines(tree, symbol) else f"{symbol} is not defined in {path}"


def code_problems(nodes: Dict[str, dict], edges: List[dict], repo_root: Path) -> List[str]:
    """Code layer rules: CodeRef ids name this repo's code and exist (when active); ``implemented_by`` points at
    a CodeRef; a CodeRef has no outgoing edge, receives only ``implemented_by`` and is not an orphan."""
    code = {nid for nid, n in nodes.items() if n.get("type") == CODE_TYPE}
    problems = [f"{nid}: ids under 'code:' are reserved for CodeRef nodes"
                for nid in sorted(nodes) if str(nid).startswith("code:") and nid not in code]
    for nid in sorted(code):
        problem = _code_ref_problem(nid, nodes[nid], repo_root)
        if problem:
            problems.append(f"{nid}: {problem}")
    targets = set()
    for e in edges:
        s, d, t = e.get("from"), e.get("to"), e.get("type")
        if t == "implemented_by" and d not in code:
            problems.append(f"edge {s}->{d}: implemented_by must point at a CodeRef of this repo")
        if s in code:
            problems.append(f"edge {s}->{d}: a CodeRef has no outgoing edge (the code graph stays in GitNexus)")
        if d in code:
            targets.add(d)
            if t != "implemented_by":
                problems.append(f"edge {s}->{d}: only implemented_by may point at a CodeRef, got {t!r}")
    problems += [f"{nid}: CodeRef with no implemented_by" for nid in sorted(code - targets)]
    return problems


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
