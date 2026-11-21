"""Trace pristine module/class-data consumers, with no patches or sample labels.

Run in the locked research image. Instance/MRO observations catch inherited
class attributes, and function global-import names propagate imported data.
This remains an approximation: retain conservative structural fallbacks.
"""

import argparse
import ast
from collections import defaultdict
import concurrent.futures
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import ModuleType

from build_coverage import InlineProcessPoolExecutor


class Recorder:
    def __init__(self, source):
        self.source = source
        self.active = None
        self.phase = None
        self.collection_file = None
        self.records = {}
        self.shared = defaultdict(set)
        self.collection = defaultdict(set)
        self.class_cache = {}
        self.attribute_cache = {}
        self.class_references = {}
        self.module_cache = {}
        self.code_cache = {}
        self.dict_cache = {}
        self.entry_owners = {}
        self.patches = []
        self.imports = self.import_graph()

    def relative(self, filename):
        if not filename or not isinstance(filename, str):
            return None
        try:
            return Path(filename).resolve().relative_to(self.source).as_posix()
        except ValueError:
            return None

    def module_path(self, name):
        if name in self.module_cache:
            return self.module_cache[name]
        module = sys.modules.get(name)
        path = self.relative(ModuleType.__getattribute__(module, "__dict__").get("__file__")) if isinstance(module, ModuleType) else None
        if path:
            self.module_cache[name] = path
        return path

    def add(self, paths):
        if self.active is not None:
            self.active["modules"].update(paths)
            if self.phase != "call":
                self.shared[self.active["test_file"]].update(paths)
        elif self.collection_file:
            self.collection[self.collection_file].update(paths)

    def note_class(self, cls, attribute):
        key = id(cls)
        # Keep identity-cache entries valid for ephemeral user-defined classes.
        self.class_references[key] = cls
        paths = self.class_cache.get(key)
        if paths is None:
            found = set()
            for parent in type.__getattribute__(cls, "__mro__"):
                path = self.module_path(type.__getattribute__(parent, "__module__"))
                if path:
                    found.add(path)
            paths = tuple(found)
            self.class_cache[key] = paths
        pair = key, attribute
        attributed = self.attribute_cache.get(pair)
        if attributed is None:
            attributed = tuple(path + "::" + attribute for path in paths)
            self.attribute_cache[pair] = attributed
        self.add(attributed)

    def note_metadata(self, value):
        if not isinstance(value, dict):
            return
        key = id(value)
        paths = self.dict_cache.get(key)
        if paths is None:
            # Modules enter sys.modules before their children. For inherited
            # metadata dictionaries, the first owner of each entry is its source.
            for name, module in tuple(sys.modules.items()):
                if name.startswith("sqlglot.typing") and isinstance(module, ModuleType):
                    namespace = ModuleType.__getattribute__(module, "__dict__")
                    table = namespace.get("EXPRESSION_METADATA")
                    path = self.module_path(name)
                    if path and isinstance(table, dict):
                        for entry in table.values():
                            if isinstance(entry, dict):
                                self.entry_owners.setdefault(id(entry), path)
            paths = tuple({self.entry_owners[id(entry)] for entry in value.values()
                           if id(entry) in self.entry_owners})
            self.dict_cache[key] = paths
        self.add(paths)

    def install_attribute_tracking(self):
        from sqlglot import expressions
        from sqlglot.dialects.dialect import Dialect, _Dialect
        from sqlglot.generator import Generator
        from sqlglot.parser import Parser
        from sqlglot.tokens import Tokenizer
        # This experiment only narrows immutable Dialect-owned fields. Other
        # receiver families retain the established v4 module map. Avoid tracing
        # millions of unrelated Expr/Parser/Tokenizer instance attribute reads.
        for base in (Dialect,):
            old = base.__getattribute__
            recorder = self

            def getter(instance, name, original=old):
                recorder.note_class(type(instance), name)
                result = original(instance, name)
                if name in ("EXPRESSION_METADATA", "expression_metadata"):
                    recorder.note_metadata(result)
                return result

            self.patches.append((base, old))
            base.__getattribute__ = getter
        old_type_getter = _Dialect.__getattribute__

        def type_getter(cls, name):
            self.note_class(cls, name)
            result = old_type_getter(cls, name)
            if name == "EXPRESSION_METADATA":
                self.note_metadata(result)
            return result

        self.patches.append((_Dialect, old_type_getter))
        _Dialect.__getattribute__ = type_getter

    def import_graph(self):
        imports = {}
        all_paths = {path.relative_to(self.source).as_posix()
                     for path in (self.source / "sqlglot").rglob("*.py")}
        for name in all_paths:
            aliases = {}
            tree = ast.parse((self.source / name).read_text("utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue
                module = node.module or ""
                if not module.startswith("sqlglot"):
                    continue
                target = module.replace(".", "/") + ".py"
                if target not in all_paths:
                    target = module.replace(".", "/") + "/__init__.py"
                if target in all_paths:
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = target
            imports[name] = aliases
        return imports

    def on_start(self, code, offset):
        paths = self.code_cache.get(code)
        if paths is None:
            name = self.relative(code.co_filename)
            aliases = self.imports.get(name, {})
            paths = tuple({aliases[variable] for variable in code.co_names if variable in aliases})
            self.code_cache[code] = paths
        self.add(paths)
        return sys.monitoring.DISABLE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/opt/sqlglot"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=550)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ.update(SKIP_INTEGRATION="0", PYTHONDONTWRITEBYTECODE="1",
                      PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    sys.dont_write_bytecode = True
    concurrent.futures.ProcessPoolExecutor = InlineProcessPoolExecutor
    import pytest
    recorder = Recorder(source)
    recorder.install_attribute_tracking()
    tool_id = next(index for index in (1, 2, 3, 4, 0, 5) if sys.monitoring.get_tool(index) is None)
    sys.monitoring.use_tool_id(tool_id, "pristine-module-consumers")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.PY_START, recorder.on_start)
    started = time.monotonic()
    collected = []
    collection_errors = []

    class Plugin:
        def pytest_collectstart(self, collector):
            path = getattr(collector, "path", None)
            if path:
                relative = recorder.relative(str(path))
                if relative and relative.endswith(".py"):
                    recorder.collection_file = relative

        def pytest_collection_finish(self, session):
            collected.extend(item.nodeid for item in session.items)
            recorder.collection_file = None

        def pytest_collectreport(self, report):
            if report.failed:
                collection_errors.append(report.nodeid)

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_protocol(self, item, nextitem):
            if time.monotonic() - started > args.max_seconds:
                pytest.exit("Module trace budget exceeded", returncode=2)
            record = {"test_file": item.nodeid.split("::")[0], "modules": set(), "outcomes": {}}
            recorder.records[item.nodeid] = record
            recorder.active = record
            recorder.phase = "setup"
            sys.monitoring.restart_events()
            try:
                yield
            finally:
                recorder.active = None
                recorder.phase = None

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_setup(self, item):
            recorder.phase = "setup"
            yield

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_call(self, item):
            recorder.phase = "call"
            yield

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_teardown(self, item, nextitem):
            recorder.phase = "teardown"
            yield

        def pytest_runtest_logreport(self, report):
            if report.nodeid in recorder.records:
                recorder.records[report.nodeid]["outcomes"][report.when] = report.outcome

    sys.monitoring.set_events(tool_id, sys.monitoring.events.PY_START)
    run_args = ["-q", "-p", "no:cacheprovider", "-p", "pytest_timeout", "--timeout=120"]
    user_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    try:
        with contextlib.redirect_stdout(sys.stderr):
            code = int(pytest.main(run_args + (user_args or ["tests"]), plugins=[Plugin()]))
    finally:
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.PY_START, None)
        sys.monitoring.free_tool_id(tool_id)
        for base, original in reversed(recorder.patches):
            base.__getattribute__ = original
    records = {}
    for test_id, record in recorder.records.items():
        modules = record["modules"] | recorder.shared[record["test_file"]] | recorder.collection[record["test_file"]]
        records[test_id] = sorted(modules)
    failed = [test_id for test_id, record in recorder.records.items() if "failed" in record["outcomes"].values()]
    payload = {"format": "pristine-class-attribute-import-consumers-v1", "tests": records,
               "collection": {name: sorted(values) for name, values in recorder.collection.items()},
               "shared": {name: sorted(values) for name, values in recorder.shared.items()},
               "pytest_exit_code": code, "failed": failed, "collection_errors": collection_errors,
               "missing": sorted(set(collected) - records.keys()),
               "elapsed_seconds": round(time.monotonic() - started, 3),
               "source_python_sha256": {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                          for folder in (source / "sqlglot", source / "tests") for path in folder.rglob("*.py")}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Module trace: {len(records)} tests, {len(failed)} failures, {payload['elapsed_seconds']} seconds", file=sys.stderr)
    return 0 if code == 0 and not failed and not collection_errors and not payload["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
