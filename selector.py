"""Blast Radius selector: pristine coverage with conservative structural fallback.

This is deliberately separate from the submission. Unknown structures, edits to
module state, imports, fixtures, new definitions, or incomplete maps select all
tests. Passing samples does not establish hidden-test recall.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scheduler import choose_workers, split
from map_codec import load_coverage

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply_patch(patch: str, source: Path) -> dict[str, tuple[str, str]]:
    """Apply strict ordinary unified hunks in memory; fail closed on ambiguity."""
    lines = patch.splitlines(keepends=True)
    results = {}
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            if lines[index].strip() and not lines[index].startswith(("diff --git ", "index ")):
                raise ValueError("unexpected content outside hunk")
            index += 1
            continue
        old_path = lines[index][4:].strip()
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError("missing new path")
        new_path = lines[index][4:].strip()
        index += 1
        if not old_path.startswith("a/") or not new_path.startswith("b/"):
            raise ValueError("new/deleted/unrecognized file")
        name = old_path[2:]
        if name != new_path[2:] or name in results or "\\" in name:
            raise ValueError("rename or duplicate file")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not name.endswith(".py"):
            raise ValueError("unhandled file")
        path = (source / name).resolve()
        if not path.is_relative_to(source.resolve()):
            raise ValueError("path escaped source")
        before = path.read_text(encoding="utf-8")
        original = before.splitlines(keepends=True)
        output = []
        consumed = 0
        hunk_count = 0
        while index < len(lines):
            match = HUNK.match(lines[index])
            if not match:
                break
            hunk_count += 1
            old_start, old_length, new_start, new_length = match.groups()
            old_length = int(old_length) if old_length is not None else 1
            new_length = int(new_length) if new_length is not None else 1
            start = int(old_start) - (1 if old_length else 0)
            if start < consumed or start > len(original):
                raise ValueError("overlapping/out of bounds hunk")
            output.extend(original[consumed:start])
            consumed = start
            if len(output) != int(new_start) - (1 if new_length else 0):
                raise ValueError("new hunk offset mismatch")
            index += 1
            old_count = new_count = 0
            while index < len(lines) and (old_count < old_length or new_count < new_length):
                line = lines[index]
                index += 1
                if not line or line[0] not in " +-":
                    raise ValueError("malformed hunk")
                # Honor a no-final-newline marker for this content line.
                if index < len(lines) and lines[index].startswith("\\ No newline"):
                    line = line.rstrip("\r\n")
                    index += 1
                value = line[1:]
                if line[0] in " -":
                    if consumed >= len(original) or original[consumed] != value:
                        raise ValueError("context mismatch")
                    consumed += 1
                    old_count += 1
                if line[0] in " +":
                    output.append(value)
                    new_count += 1
            if old_count != old_length or new_count != new_length:
                raise ValueError("hunk length mismatch")
        if not hunk_count:
            raise ValueError("file has no hunks")
        output.extend(original[consumed:])
        results[name] = before, "".join(output)
    if not results:
        raise ValueError("patch has no recognized hunks")
    # A mixed binary/text diff must never silently discard its binary section.
    sections = sum(line.startswith("diff --git ") for line in lines)
    if sections and sections != len(results):
        raise ValueError("unhandled diff section")
    return results


def changed_functions(before: str, after: str) -> list[tuple[int, int]]:
    """Accept only body changes to existing functions; retain module structure."""
    old_tree, new_tree = ast.parse(before), ast.parse(after)

    def definitions(tree):
        shapes = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                shell = copy.deepcopy(node)
                shell.body = [ast.Pass()]
                shapes.append(ast.dump(shell, include_attributes=False))
            elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                shapes.append(ast.dump(node, include_attributes=False))
        return shapes

    if definitions(old_tree) != definitions(new_tree):
        raise ValueError("edit changes definitions or imports")
    old_functions = []
    new_functions = []

    class StripBodies(ast.NodeTransformer):
        def __init__(self, found):
            self.found = found

        def visit_FunctionDef(self, node):
            self.found.append((ast.dump(node, include_attributes=False), node.lineno, node.end_lineno))
            node.body = [ast.Pass()]
            return node

        visit_AsyncFunctionDef = visit_FunctionDef

    old_skeleton = ast.dump(StripBodies(old_functions).visit(old_tree), include_attributes=False)
    new_skeleton = ast.dump(StripBodies(new_functions).visit(new_tree), include_attributes=False)
    if old_skeleton != new_skeleton or len(old_functions) != len(new_functions):
        raise ValueError("edit changes module structure or function signature")
    changed = [(old[1], old[2]) for old, new in zip(old_functions, new_functions) if old[0] != new[0]]
    # AST equivalence does not prove raw-source readers cannot fail. We currently
    # keep the safe baseline for comment-only edits rather than infer harmlessness.
    if not changed:
        raise ValueError("no changed executable function body")
    return changed


def select(tests: list[dict], edits: dict, coverage: dict,
           source_hashes: dict | None = None) -> tuple[list[dict], str]:
    recorded = coverage["tests"]
    # Any unrecorded incoming ID or bad baseline is an all-tests fallback.
    if (coverage.get("failed") or coverage.get("collection_errors")
            or coverage.get("interrupted")
            or any(test["id"] not in recorded for test in tests)):
        return tests, "incomplete or failing baseline"
    for name, texts in edits.items():
        expected = coverage.get("source_python_sha256", {}).get(name)
        # Synthetic unit maps may omit hashes; real recorded maps always bind
        # every source file. Check before using a real map.
        actual = (source_hashes or {}).get(name, hashlib.sha256(texts[0].encode("utf-8")).hexdigest())
        if coverage.get("format") and expected != actual:
            return tests, "source hash mismatch"
    spans = {name: changed_functions(*texts) for name, texts in edits.items()}
    for name, ranges in spans.items():
        imported = coverage.get("collection_lines", {}).get(name, [])
        # Module execution records def headers; only body execution is evidence
        # that an edited function was actually called during collection.
        if any((start < line <= end) or (start == end == line)
               for line in imported for start, end in ranges):
            return tests, "function executes during collection"
    selected = []
    for test in tests:
        context = recorded[test["id"]]
        hits = False
        for name, ranges in spans.items():
            # Source readers and tests in edited test modules are consumers even
            # when edited code never executed in the pristine run.
            if name in context.get("opened", []) or test["file"] == name:
                hits = True
            if any(start <= line <= end
                   for line in context.get("lines", {}).get(name, [])
                   for start, end in ranges):
                hits = True
        if hits:
            selected.append(test)
    if not selected:
        return tests, "no mapped consumers"
    return selected, "function coverage plus source readers"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument("--source", type=Path, default=Path("/opt/sqlglot"))
    parser.add_argument("--coverage", type=Path, default=Path("/app/coverage.json"))
    parser.add_argument("--strategy", choices=("starter", "balanced", "coverage"), default="coverage")
    options = parser.parse_args()
    tests = json.loads((options.data / "tests.json").read_text("utf-8"))["tests"]
    coverage = (load_coverage(options.coverage)
                if options.strategy == "coverage" else None)
    for patch in sorted((options.data / "commits").glob("*.patch")):
        try:
            if options.strategy != "coverage":
                workers = split(tests, 3) if options.strategy == "starter" else choose_workers(tests)
                print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
                continue
            edits = apply_patch(patch.read_text("utf-8"), options.source)
            source_hashes = {name: hashlib.sha256((options.source / name).read_bytes()).hexdigest()
                             for name in edits}
            selected, reason = select(tests, edits, coverage, source_hashes)
        except (ValueError, OSError, SyntaxError, KeyError) as error:
            selected, reason = tests, f"fallback: {error}"
        print(json.dumps({"commit": patch.stem, "workers": choose_workers(selected)}, separators=(",", ":")))
        print(json.dumps({"commit": patch.stem, "selected": len(selected), "reason": reason}), file=sys.stderr)


if __name__ == "__main__":
    main()


