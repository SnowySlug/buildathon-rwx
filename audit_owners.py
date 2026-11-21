"""Verify static field ownership against actual pristine imported classes."""

import argparse
import importlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from sqlglot.dialects.dialect import Dialect
    inventory = json.loads(args.inventory.read_text("utf-8"))
    failures = []
    owners = 0
    for field, description in inventory["candidate_fields"].items():
        for owner in description["owners"]:
            owners += 1
            module = owner["path"][:-3].replace("/", ".").removesuffix(".__init__")
            target = importlib.import_module(module)
            for component in owner["owner"].removeprefix(module + ".").split("."):
                target = vars(target)[component]
            if not isinstance(target, type) or not issubclass(target, Dialect):
                failures.append({"owner": owner["owner"], "field": field, "error": "not Dialect"})
            elif field not in vars(target):
                failures.append({"owner": owner["owner"], "field": field, "error": "not directly declared"})
            elif type(vars(target)[field]) not in (str, int, float, bool, type(None)):
                failures.append({"owner": owner["owner"], "field": field, "error": "nonliteral runtime value"})
    result = {"fields": len(inventory["candidate_fields"]), "owners": owners, "failures": failures}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
