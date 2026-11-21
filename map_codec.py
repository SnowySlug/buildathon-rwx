"""Decode an ordinary JSON pristine function-coverage map."""

import json


def load_coverage(path):
    coverage = json.loads(path.read_text("utf-8"))
    if coverage.get("encoding") != "outer-function-bitsets-v1":
        return coverage
    paths = coverage["paths"]
    starts = coverage["function_starts"]
    decoded = {}
    for test_id, (packed_lines, opened_ids) in coverage["tests"].items():
        lines = {}
        entries = (entry.split(":", 1) for entry in packed_lines.split(";")) if packed_lines else []
        for path_hexadecimal, hexadecimal in entries:
            path_id = int(path_hexadecimal, 16)
            mask = int(hexadecimal, 16)
            function_lines = starts[str(path_id)]
            values = []
            while mask:
                index = (mask & -mask).bit_length() - 1
                values.append(function_lines[index])
                mask &= mask - 1
            lines[paths[path_id]] = values
        decoded[test_id] = {"lines": lines, "opened": [paths[index] for index in opened_ids]}
    coverage["tests"] = decoded
    return coverage
