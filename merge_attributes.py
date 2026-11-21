"""Add pristine immutable-Dialect-field bitsets to an existing validated map."""

import argparse
import json
from pathlib import Path


def merge(compact, trace, inventory):
    if (trace["pytest_exit_code"] or trace["failed"] or trace["collection_errors"]
            or trace["missing"] or trace["source_python_sha256"] != compact["source_python_sha256"]):
        raise ValueError("Incomplete, failing, or mismatched pristine trace")
    ids = sorted(compact["tests"])
    if set(ids) - trace["tests"].keys():
        raise ValueError("Unknown test IDs")
    collection = {item for items in trace["collection"].values() for item in items}
    fields = {}
    for field, description in inventory["candidate_fields"].items():
        for owner in description["owners"]:
            path = owner["path"]
            module = path[:-3].replace("/", ".").removesuffix(".__init__")
            qualified = owner["owner"].removeprefix(module + ".") + "." + field
            key = path + "::" + field
            if key in collection:
                continue
            # Reading a raw class/instance namespace can observe any field.
            witnesses = {key, path + "::__dict__"}
            mask = sum(1 << index for index, test_id in enumerate(ids)
                       if witnesses.intersection(trace["tests"][test_id]))
            if not mask:
                continue  # Unobserved fields retain the established module mask.
            fields.setdefault(path, {})[qualified] = format(mask, "x")
    compact["dialect_literal_field_bits"] = fields
    compact["field_trace_provenance"] = {
        "format": trace["format"], "tests": len(trace["tests"]),
        "elapsed_seconds": trace["elapsed_seconds"],
        "collection_read_fields_fallback": True, "raw_namespace_consumers": True,
        "eligibility": "immutable same-type literal RHS only; all other AST unchanged",
    }
    return compact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("map", "trace", "inventory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = merge(json.loads(args.map.read_text("utf-8")), json.loads(args.trace.read_text("utf-8")),
                   json.loads(args.inventory.read_text("utf-8")))
    args.output.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"field_paths": len(result["dialect_literal_field_bits"]),
                      "fields": sum(map(len, result["dialect_literal_field_bits"].values())),
                      "bytes": args.output.stat().st_size}))
