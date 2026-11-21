"""Conservative Blast Radius baseline: select every test, optimize worker cost.

Only tests.json and patch filenames are read. Sample answers never enter this
program or the submission image. No third-party packages are required.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def milliseconds(test: dict) -> int:
    """Match the official score.py's integer arithmetic."""
    return math.floor(test["seconds"] * 1000 + 0.5)


def split(tests: list[dict], worker_count: int) -> list[list[int]]:
    """Original starter's floating-point longest-processing-time schedule."""
    workers: list[list[int]] = [[] for _ in range(worker_count)]
    loads = [0.0] * worker_count
    for test in sorted(tests, key=lambda item: item["seconds"], reverse=True):
        lightest = loads.index(min(loads))
        workers[lightest].append(test["number"])
        loads[lightest] += test["seconds"]
    return workers


def schedule_cost(workers: list[list[int]], tests: list[dict]) -> int:
    durations = {test["number"]: milliseconds(test) for test in tests}
    occupied = [worker for worker in workers if worker]
    return (max(sum(durations[number] for number in worker) for worker in occupied)
            + 2000 * len(occupied)) if occupied else 0


def choose_workers(tests: list[dict]) -> list[list[int]]:
    """Try all legal worker counts using integer LPT; retain the cheapest.

    Include the original schedule as a fallback: this cannot increase its exact
    simulated cost for any supplied test catalog. This does not claim optimal
    multiprocessor scheduling, which is NP-hard.
    """
    if not tests:
        return []
    ranked = sorted(tests, key=lambda test: (-milliseconds(test), test["number"]))
    candidates = [split(tests, 3)]
    for count in range(1, min(8, len(tests)) + 1):
        workers: list[list[int]] = [[] for _ in range(count)]
        loads = [0] * count
        for test in ranked:
            lightest = min(range(count), key=lambda index: (loads[index], index))
            workers[lightest].append(test["number"])
            loads[lightest] += milliseconds(test)
        candidates.append(workers)
    return min(candidates, key=lambda workers: (schedule_cost(workers, tests), len(workers)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument("--strategy", choices=("starter", "balanced"), default="balanced")
    options = parser.parse_args()
    tests = json.loads((options.data / "tests.json").read_text(encoding="utf-8"))["tests"]
    workers = split(tests, 3) if options.strategy == "starter" else choose_workers(tests)
    for patch in sorted((options.data / "commits").glob("*.patch")):
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
    print(f"selected {len(tests)} tests; strategy={options.strategy}", file=sys.stderr)


if __name__ == "__main__":
    main()
