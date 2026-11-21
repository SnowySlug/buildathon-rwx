"""Merge only pristine class/import observations into a compact function map."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--consumers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    coverage = json.loads(args.coverage.read_text("utf-8"))
    raw = args.consumers.read_bytes()
    consumers = json.loads(raw)
    if consumers["pytest_exit_code"] != 0 or any(consumers[key] for key in ("failed", "missing", "collection_errors")):
        raise RuntimeError("Pristine consumer trace must pass completely")
    if coverage["source_python_sha256"] != consumers["source_python_sha256"]:
        raise RuntimeError("Pristine source hashes disagree")
    order = {test_id: index for index, test_id in enumerate(sorted(coverage["tests"]))}
    if set(order) != set(consumers["tests"]):
        raise RuntimeError("Pristine test IDs disagree")
    bits = {}
    for test_id, paths in consumers["tests"].items():
        for name in paths:
            if name in coverage["source_python_sha256"]:
                bits[name] = bits.get(name, 0) | (1 << order[test_id])
    coverage["module_test_bits"] = {name: format(value, "x") for name, value in sorted(bits.items())}
    coverage["module_trace"] = {"format": consumers["format"],
                                "source_sha256": hashlib.sha256(raw).hexdigest(),
                                "elapsed_seconds": consumers["elapsed_seconds"],
                                "test_order": "lexicographic test id", "failed": []}
    args.output.write_text(json.dumps(coverage, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
