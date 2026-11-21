"""Record only pristine identity-comparison operand domains, not mutant results."""

import argparse
import ast
from collections import defaultdict
import concurrent.futures
import contextlib
from enum import Enum, Flag
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_coverage import InlineProcessPoolExecutor


class Profile:
    def __init__(self):
        self.active = None
        self.file = None
        self.phase = None
        self.records = defaultdict(lambda: defaultdict(set))
        self.shared = defaultdict(lambda: defaultdict(set))
        self.collection = defaultdict(lambda: defaultdict(set))
        self.domains = {}
        self.sites = {}
        self.class_ids = {}
        self.class_references = {}

    def domain(self, value):
        cls = type(value)
        identity = id(cls)
        if identity not in self.class_ids:
            self.class_ids[identity] = len(self.class_ids)
            self.class_references[identity] = cls
        ordinal = self.class_ids[identity]
        eq = type.__getattribute__(cls, "__eq__")
        ne = type.__getattribute__(cls, "__ne__")
        label = type.__getattribute__(cls, "__module__") + "." + type.__getattribute__(cls, "__qualname__")
        kind = "unknown"
        if value is None:
            kind = "none"
        elif eq is object.__eq__ and ne is object.__ne__:
            kind = "object_identity"
        elif issubclass(cls, Enum) and not issubclass(cls, Flag):
            # Canonical Enum members with distinct immutable underlying primitive
            # values have equality iff identity. No equality operation is tested
            # against a proposed replacement operator here.
            members = tuple(type.__getattribute__(cls, "_member_map_").values())
            canonical = any(value is member for member in members)
            if eq is str.__eq__ and ne is str.__ne__ and canonical:
                primitives = {str.__str__(member) for member in members}
                if len(primitives) == len({id(member) for member in members}):
                    kind = "canonical_str_enum"
            elif eq is int.__eq__ and ne is int.__ne__ and canonical:
                primitives = {int.__int__(member) for member in members}
                if len(primitives) == len({id(member) for member in members}):
                    kind = "canonical_int_enum"
        key = label + "|" + kind + "|" + str(ordinal)
        self.domains[key] = {"type": label, "kind": kind, "class_id": ordinal}
        return key

    def compare(self, site, left, right, negate):
        pair = self.domain(left), self.domain(right)
        if self.active is not None:
            self.records[self.active][site].add(pair)
            if self.phase != "call":
                self.shared[self.file][site].add(pair)
        elif self.file:
            self.collection[self.file][site].add(pair)
        return (left is not right) if negate else (left is right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/opt/sqlglot"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=420)
    parser.add_argument("--paths", nargs="+", default=["sqlglot/dialects/dialect.py", "sqlglot/executor/context.py"])
    args = parser.parse_args()
    source = args.source.resolve()
    paths = {name[:-3].replace("/", "."): name for name in args.paths}
    profile = Profile()
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ.update(SKIP_INTEGRATION="0", PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    concurrent.futures.ProcessPoolExecutor = InlineProcessPoolExecutor

    class Loader(importlib.abc.Loader):
        def __init__(self, name): self.name = name
        def create_module(self, spec): return None
        def exec_module(self, module):
            name = self.name
            text = (source / name).read_bytes()
            tree = compile(text, str(source / name), "exec", ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS)
            class Transform(ast.NodeTransformer):
                def visit_Compare(self, node):
                    self.generic_visit(node)
                    if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot)):
                        site = name + ":" + str(node.lineno) + ":" + str(node.col_offset)
                        profile.sites[site] = {"path": name, "line": node.lineno, "col": node.col_offset,
                            "expression": ast.dump(node, include_attributes=False)}
                        call = ast.Call(func=ast.Name(id="__rwx_comparison_profile__", ctx=ast.Load()),
                            args=[ast.Constant(site), node.left, node.comparators[0], ast.Constant(isinstance(node.ops[0], ast.IsNot))], keywords=[])
                        return ast.copy_location(call, node)
                    return node
            tree = ast.fix_missing_locations(Transform().visit(tree))
            module.__dict__["__rwx_comparison_profile__"] = profile.compare
            exec(compile(tree, str(source / name), "exec"), module.__dict__)

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            name = paths.get(fullname)
            return importlib.util.spec_from_file_location(fullname, source / name, loader=Loader(name)) if name else None

    sys.meta_path.insert(0, Finder())
    import pytest
    started = time.monotonic()
    collected = []
    failed = set()
    errors = []
    class Plugin:
        def pytest_collectstart(self, collector):
            path = getattr(collector, "path", None)
            if path:
                try: profile.file = Path(path).relative_to(source).as_posix()
                except ValueError: pass
        def pytest_collection_finish(self, session):
            collected.extend(item.nodeid for item in session.items)
            profile.file = None
        def pytest_collectreport(self, report):
            if report.failed: errors.append(report.nodeid)
        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_protocol(self, item, nextitem):
            if time.monotonic() - started > args.max_seconds: pytest.exit("type trace budget exceeded", returncode=2)
            profile.active = item.nodeid
            profile.file = item.nodeid.split("::")[0]
            profile.phase = "setup"
            profile.records[item.nodeid]
            try: yield
            finally: profile.active = profile.file = profile.phase = None
        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_call(self, item):
            profile.phase = "call"
            yield
            profile.phase = "teardown"
        def pytest_runtest_logreport(self, report):
            if report.failed: failed.add(report.nodeid)
    with contextlib.redirect_stdout(sys.stderr):
        code = int(pytest.main(["tests", "-q", "-p", "no:cacheprovider", "-p", "pytest_timeout", "--timeout=120"], plugins=[Plugin()]))
    def serialize(records):
        return {key: {site: sorted(values) for site, values in sites.items()} for key, sites in records.items()}
    result = {"format": "pristine-identity-operand-domains-v1", "tests": serialize(profile.records),
        "shared": serialize(profile.shared), "collection": serialize(profile.collection),
        "domains": profile.domains, "sites": profile.sites, "failed": sorted(failed), "collection_errors": errors,
        "missing": sorted(set(collected)-profile.records.keys()), "pytest_exit_code": code,
        "elapsed_seconds": time.monotonic()-started,
        "source_python_sha256": {p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for root in ("sqlglot", "tests") for p in (source/root).rglob("*.py")}}
    args.output.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"tests":len(result["tests"]),"failed":result["failed"],"missing":len(result["missing"]),"elapsed":result["elapsed_seconds"]}))
    return bool(code or failed or errors or result["missing"])


if __name__ == "__main__":
    raise SystemExit(main())
