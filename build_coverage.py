"""Research-only dependency map from an unmodified, pinned sqlglot checkout.

Run inside the Python 3.13 research image with the official requirements lock.
This executes process-pool work synchronously with serialization round trips.
Other subprocesses are NOT traced, so the result is not a sound impact oracle.
No patches, sample labels, or competition answers are read by this program.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import time
from collections import defaultdict
from multiprocessing.reduction import ForkingPickler


class InlineProcessPoolExecutor(concurrent.futures.Executor):
    """Execute work immediately, preserving Futures and transport serialization."""

    def __init__(
        self, max_workers=None, mp_context=None, initializer=None, initargs=(),
        *, max_tasks_per_child=None,
    ):
        self._shutdown = False
        self._initializer = initializer
        self._initargs = initargs
        self._initialized = False
        self._initializer_error = None

    def submit(self, fn, /, *args, **kwargs):
        if self._shutdown:
            raise RuntimeError("cannot schedule new futures after shutdown")
        future = concurrent.futures.Future()
        if not future.set_running_or_notify_cancel():
            return future
        try:
            if not self._initialized:
                self._initialized = True
                try:
                    if self._initializer is not None:
                        initializer, initargs = self._roundtrip(
                            (self._initializer, self._initargs)
                        )
                        initializer(*initargs)
                except BaseException as error:
                    self._initializer_error = error
            if self._initializer_error is not None:
                raise self._initializer_error
            # ProcessPoolExecutor pickles its task envelope and its result.
            # Besides copying arguments, this can call application code such as
            # Expr.__reduce__, serde.dump and serde.load. Omitting it loses real
            # dependencies even if the directly called function behaves alike.
            task_fn, task_args, task_kwargs = self._roundtrip((fn, args, kwargs))
            result = task_fn(*task_args, **task_kwargs)
            future.set_result(self._roundtrip(result))
        except BaseException as error:
            try:
                transported_error = self._roundtrip(error)
            except BaseException as serialization_error:
                transported_error = serialization_error
            future.set_exception(transported_error)
        return future

    @staticmethod
    def _roundtrip(value):
        return ForkingPickler.loads(ForkingPickler.dumps(value))

    # Executor.map supplies real Future semantics, including exception delivery,
    # chunksize acceptance, timeout and ordered results. Work completes in submit.
    def shutdown(self, wait=True, *, cancel_futures=False):
        self._shutdown = True


class Recorder:
    def __init__(self, source):
        self.source = source
        self.prefix = str(source) + os.sep
        self.path_cache = {}
        self.code_cache = {}
        self.active = None
        self.phase = None
        self.collection_lines = defaultdict(set)
        self.collection_opened = set()
        self.shared_lines = defaultdict(lambda: defaultdict(set))
        self.shared_opened = defaultdict(set)
        self.monitoring = sys.monitoring
        self.tool_id = None
        self.enabled = False

    def relative_path(self, filename):
        if not isinstance(filename, (str, bytes, os.PathLike)):
            return None
        filename = os.fsdecode(filename)
        if filename in self.path_cache:
            return self.path_cache[filename]
        if filename.startswith("<"):
            result = None
        else:
            absolute = os.path.abspath(filename)
            result = (
                os.path.relpath(absolute, self.source).replace(os.sep, "/")
                if absolute.startswith(self.prefix) else None
            )
        self.path_cache[filename] = result
        return result

    def on_start(self, code, offset):
        relative = self.code_cache.get(code)
        if relative is None:
            relative = self.relative_path(code.co_filename) or ""
            self.code_cache[code] = relative
        if relative:
            self.monitoring.set_local_events(
                self.tool_id, code, self.monitoring.events.LINE
            )
        return self.monitoring.DISABLE

    def on_line(self, code, line):
        relative = self.code_cache.get(code)
        if relative:
            if self.active is None:
                self.collection_lines[relative].add(line)
            else:
                self.active["lines"][relative].add(line)
                if self.phase != "call":
                    self.shared_lines[self.active["test_file"]][relative].add(line)
        return self.monitoring.DISABLE

    def audit(self, event, args):
        if self.enabled and event == "open" and args:
            relative = self.relative_path(args[0])
            if relative is not None:
                if self.active is None:
                    self.collection_opened.add(relative)
                else:
                    self.active["opened"].add(relative)
                    if self.phase != "call":
                        self.shared_opened[self.active["test_file"]].add(relative)

    def start(self):
        for candidate in (1, 2, 3, 4, 0, 5):
            if self.monitoring.get_tool(candidate) is None:
                self.monitoring.use_tool_id(candidate, "blast-radius-research")
                self.tool_id = candidate
                break
        if self.tool_id is None:
            raise RuntimeError("No sys.monitoring tool ID is available")
        self.monitoring.register_callback(
            self.tool_id, self.monitoring.events.PY_START, self.on_start
        )
        self.monitoring.register_callback(
            self.tool_id, self.monitoring.events.LINE, self.on_line
        )
        sys.addaudithook(self.audit)
        self.enabled = True
        self.monitoring.set_events(self.tool_id, self.monitoring.events.PY_START)

    def stop(self):
        self.enabled = False
        self.monitoring.set_events(self.tool_id, 0)
        for code in self.code_cache:
            self.monitoring.set_local_events(self.tool_id, code, 0)
        self.monitoring.register_callback(self.tool_id, self.monitoring.events.PY_START, None)
        self.monitoring.register_callback(self.tool_id, self.monitoring.events.LINE, None)
        self.monitoring.free_tool_id(self.tool_id)


def sorted_lines(lines):
    return {path: sorted(numbers) for path, numbers in sorted(lines.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/opt/sqlglot"))
    parser.add_argument("--output", type=Path, default=Path(".local/coverage.json"))
    parser.add_argument("--max-seconds", type=float, default=480)
    parser.add_argument("--test-timeout", type=float, default=90)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not hasattr(sys, "monitoring"):
        parser.error("Python 3.12+ is required; use the official Python 3.13 image")
    source = args.source.resolve()
    output = args.output.resolve()  # Preserve caller-relative output before chdir.
    if not (source / "sqlglot").is_dir() or not (source / "tests").is_dir():
        parser.error("--source must contain the pristine sqlglot/ and tests/ directories")
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ["SKIP_INTEGRATION"] = "0"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.dont_write_bytecode = True

    # Imported test modules use `from concurrent.futures import ...`, so replace
    # the public export BEFORE pytest imports or collects any tests.
    original_executor = concurrent.futures.ProcessPoolExecutor
    concurrent.futures.ProcessPoolExecutor = InlineProcessPoolExecutor
    import pytest

    recorder = Recorder(source)
    started = time.monotonic()
    records = {}
    collected = []
    collection_errors = []
    interrupted = []
    timeout_available = importlib.util.find_spec("pytest_timeout") is not None

    class Plugin:
        @pytest.hookimpl
        def pytest_collection_finish(self, session):
            collected.extend(item.nodeid for item in session.items)

        @pytest.hookimpl
        def pytest_collectreport(self, report):
            if report.failed:
                collection_errors.append({"nodeid": report.nodeid, "error": str(report.longrepr)})

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_protocol(self, item, nextitem):
            if time.monotonic() - started >= args.max_seconds:
                interrupted.append("research wall-time budget reached")
                pytest.exit(interrupted[-1], returncode=2)
            record = {
                "test_file": item.nodeid.split("::", 1)[0],
                "lines": defaultdict(set), "opened": set(), "outcomes": {},
            }
            records[item.nodeid] = record
            recorder.active = record
            recorder.phase = "setup"
            recorder.monitoring.restart_events()
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

        @pytest.hookimpl
        def pytest_runtest_logreport(self, report):
            if report.nodeid in records:
                records[report.nodeid]["outcomes"][report.when] = report.outcome

    run_args = ["-q", "-p", "no:cacheprovider", "--capture=fd"]
    if timeout_available:
        run_args += ["-p", "pytest_timeout", f"--timeout={args.test_timeout:g}"]
    user_args = args.pytest_args
    if user_args[:1] == ["--"]:
        user_args = user_args[1:]
    run_args += user_args or ["tests"]
    exit_code = 3
    recorder.start()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            exit_code = int(pytest.main(run_args, plugins=[Plugin()]))
    except BaseException as error:
        interrupted.append(f"{type(error).__name__}: {error}")
        print(f"Coverage interrupted: {interrupted[-1]}", file=sys.stderr)
    finally:
        recorder.stop()
        concurrent.futures.ProcessPoolExecutor = original_executor

    # Unittest/pytest shared setup executes once, often in the first item's
    # context. Conservatively include every non-call observation from that file.
    for record in records.values():
        test_file = record["test_file"]
        for filename, numbers in recorder.shared_lines[test_file].items():
            record["lines"][filename].update(numbers)
        record["opened"].update(recorder.shared_opened[test_file])
        record["lines"] = sorted_lines(record["lines"])
        record["opened"] = sorted(record["opened"])

    failed = sorted(nodeid for nodeid, record in records.items()
                    if "failed" in record["outcomes"].values())
    skipped = sorted(nodeid for nodeid, record in records.items()
                     if "skipped" in record["outcomes"].values())
    missing = sorted(set(collected) - records.keys())
    warnings = [
        "Research-only map: not a sound guarantee of impact or test outcomes.",
        "ProcessPoolExecutor runs synchronously with ForkingPickler task/initializer/result/exception round trips; worker isolation and scheduling are not emulated.",
        "Other subprocesses and native-library file reads are not traced.",
        "Import/collection observations are separate and need consumer propagation.",
        "New branches, dispatch changes, import-time constants and source edits need structural fallbacks.",
    ]
    if not timeout_available:
        warnings.append("pytest-timeout unavailable; individual test duration is not bounded.")
    if sys.version_info[:2] != (3, 13):
        warnings.append("Python differs from the official Python 3.13 execution environment.")
    payload = {
        "format": "blast-radius-pristine-coverage-v2-pickle",
        "research": True, "incomplete": True, "warnings": warnings,
        "python": platform.python_version(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "pytest_exit_code": exit_code,
        "source_python_sha256": {
            path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in (source / "sqlglot", source / "tests")
            for path in sorted(folder.rglob("*.py"))
        },
        "collected": collected, "tests": records,
        "failed": failed, "skipped": skipped, "unexecuted": missing,
        "collection_errors": collection_errors, "interrupted": interrupted,
        "collection_lines": sorted_lines(recorder.collection_lines),
        "collection_opened": sorted(recorder.collection_opened),
        "shared_setup_by_test_file": {
            path: {"lines": sorted_lines(lines),
                   "opened": sorted(recorder.shared_opened[path])}
            for path, lines in sorted(recorder.shared_lines.items())
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Coverage map: {len(records)}/{len(collected)} tests, {len(failed)} failed, "
          f"{len(skipped)} skipped, {output.stat().st_size} bytes -> {output}", file=sys.stderr)
    # Complete traversals may include instrumented-test failures. Preserve them
    # explicitly in the map, without preventing inspection of the artifact.
    return 0 if exit_code in (0, 1) and not missing and not collection_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
