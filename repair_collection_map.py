"""Separate pristine function declaration events from actual body execution."""

import ast
import argparse
import bisect
import hashlib
import json
from pathlib import Path


def functions(tree):
    found = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            found.append(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    return found


def attribute_collection_event(node, observed):
    begin, end = node.lineno, node.end_lineno
    body = node.body[0].lineno
    nontrivial = any(not isinstance(stmt, ast.Pass) and not (
        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)) for stmt in node.body)
    safe = (not isinstance(node, ast.AsyncFunctionDef) and begin < body and nontrivial
            and not any(isinstance(child, (ast.Yield, ast.YieldFrom, ast.Await)) for child in ast.walk(node)))
    index = bisect.bisect_left(observed, body if safe else begin)
    witness = observed[index] if index < len(observed) and observed[index] <= end else None
    return witness, not safe, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-map", type=Path, required=True)
    parser.add_argument("--compact-map", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw_path = args.raw_map
    raw = json.loads(raw_path.read_text("utf-8"))
    coverage = json.loads(args.compact_map.read_text("utf-8"))
    source = args.source
    repaired = {}
    conservative = {}
    verified = 0
    for name, expected in coverage["source_python_sha256"].items():
        data = (source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Source mismatch: " + name)
        observed = raw["collection_lines"].get(name, [])
        witnesses = set()
        ambiguous = []
        for node in functions(ast.parse(data.decode("utf-8"))):
            begin, end = node.lineno, node.end_lineno
            witness, ambiguous_event, body = attribute_collection_event(node, observed)
            if witness is not None:
                witnesses.add(witness)
                if ambiguous_event:
                    ambiguous.append([begin, end])
            if not ambiguous_event:
                # No signature/header line is ever presented as body execution.
                old_body_hit = any(body <= line <= end for line in observed)
                new_hit = any(body <= line <= end for line in witnesses)
                if old_body_hit != new_hit:
                    raise RuntimeError(f"Body coverage changed: {name}:{begin}")
                verified += 1
        if witnesses:
            repaired[name] = sorted(witnesses)
        if ambiguous:
            conservative[name] = ambiguous
    coverage["collection_lines"] = repaired
    coverage["collection_conservative_spans"] = conservative
    coverage["collection_attribution"] = {
        "source_map_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "verified_body_intervals": verified,
        "rule": "function signature/default events are distinct from normal function body execution; ambiguous generators/async/one-line/doc-only cases retain fallback",
    }
    output = args.output
    output.write_text(json.dumps(coverage, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Repaired collection coverage: {verified} normal function intervals; {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
