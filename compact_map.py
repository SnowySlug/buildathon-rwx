"""Losslessly compact a pristine map for this selector's outer-function queries.

Each test/path retains one real executed line per outer function. The selector
only queries whether any line falls inside a changed outer function, so this
preserves every possible accepted query, independently of sample patches.
"""

import argparse
import ast
import bisect
import hashlib
import json
from pathlib import Path


def outer_spans(text):
    spans = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            spans.append((node.lineno, node.end_lineno))

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(ast.parse(text))
    return sorted(spans)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoding", choices=("witness", "bitset"), default="bitset")
    options = parser.parse_args()
    original_bytes = options.input.read_bytes()
    original = json.loads(original_bytes)
    functions = {}
    for name, expected in original["source_python_sha256"].items():
        data = (options.source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Source mismatch: {name}")
        functions[name] = outer_spans(data.decode("utf-8"))
    compact = {key: original[key] for key in (
        "format", "source_python_sha256", "collection_lines", "collection_opened",
        "failed", "collection_errors", "interrupted",
    )}
    compact["tests"] = {}
    compact_collection = {}
    collection_queries = 0
    for name, spans in functions.items():
        values = original["collection_lines"].get(name, [])
        witnesses = set()
        for start, end in spans:
            position = bisect.bisect_left(values, start if start == end else start + 1)
            old_hit = position < len(values) and values[position] <= end
            if old_hit:
                witnesses.add(values[position])
            collection_queries += 1
        if witnesses:
            compact_collection[name] = sorted(witnesses)
        for start, end in spans:
            old_position = bisect.bisect_left(values, start if start == end else start + 1)
            new_position = bisect.bisect_left(compact_collection.get(name, []), start if start == end else start + 1)
            old_hit = old_position < len(values) and values[old_position] <= end
            candidates = compact_collection.get(name, [])
            new_hit = new_position < len(candidates) and candidates[new_position] <= end
            if old_hit != new_hit:
                raise RuntimeError(f"Compaction changed collection query: {name}:{start}")
    compact["collection_lines"] = compact_collection
    queries = 0
    retained = 0
    original_line_count = 0
    for test_id, record in original["tests"].items():
        compressed_lines = {}
        for name, lines in record["lines"].items():
            values = sorted(set(lines))
            original_line_count += len(values)
            witnesses = set()
            for start, end in functions.get(name, []):
                index = bisect.bisect_left(values, start)
                if index < len(values) and values[index] <= end:
                    witnesses.add(values[index])
            witness_values = sorted(witnesses)
            # Prove equivalence for EVERY possible accepted outer-function span,
            # rather than just spans edited by the organizer's sample patches.
            for start, end in functions.get(name, []):
                left = bisect.bisect_left(values, start)
                right = bisect.bisect_left(witness_values, start)
                old_hit = left < len(values) and values[left] <= end
                new_hit = right < len(witness_values) and witness_values[right] <= end
                if old_hit != new_hit:
                    raise RuntimeError(f"Compaction changed coverage query: {test_id} {name}:{start}")
                queries += 1
            if witness_values:
                compressed_lines[name] = witness_values
                retained += len(witness_values)
        compact["tests"][test_id] = {"lines": compressed_lines, "opened": record["opened"]}
    compact["compaction"] = {
        "method": "one actual executed witness per outer-function interval",
        "source_map_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "verified_test_file_function_queries": queries,
        "original_executed_line_entries": original_line_count,
        "retained_line_entries": retained,
        "verified_collection_function_queries": collection_queries,
    }
    if options.encoding == "bitset":
        paths = sorted(set(functions) | {path for record in compact["tests"].values()
                                       for path in record["opened"]})
        path_ids = {path: index for index, path in enumerate(paths)}
        packed_tests = {}
        for test_id, record in compact["tests"].items():
            packed_lines = []
            for name, witnesses in record["lines"].items():
                mask = 0
                for index, (start, end) in enumerate(functions[name]):
                    position = bisect.bisect_left(witnesses, start)
                    if position < len(witnesses) and witnesses[position] <= end:
                        mask |= 1 << index
                if mask:
                    packed_lines.append([path_ids[name], format(mask, "x")])
            packed_tests[test_id] = [";".join(f"{file_id:x}:{mask}" for file_id, mask in packed_lines),
                                    [path_ids[path] for path in record["opened"]]]
        compact["tests"] = packed_tests
        compact["encoding"] = "outer-function-bitsets-v1"
        compact["paths"] = paths
        compact["function_starts"] = {str(path_ids[name]): [start for start, end in spans]
                                      for name, spans in functions.items() if spans}
    encoded = (json.dumps(compact, separators=(",", ":")) + "\n").encode("utf-8")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_bytes(encoded)
    print(json.dumps({"original_bytes": len(original_bytes), "compact_bytes": len(encoded),
                      **compact["compaction"]}, indent=2))


if __name__ == "__main__":
    main()
