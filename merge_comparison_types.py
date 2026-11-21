"""Preserve pristine operand type domains and shared contexts without answers."""

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("map", "trace", "output"):
        p.add_argument("--"+name, type=Path, required=True)
    args = p.parse_args()
    compact = json.loads(args.map.read_text("utf-8"))
    trace = json.loads(args.trace.read_text("utf-8"))
    if (trace["failed"] or trace["missing"] or trace["collection_errors"] or trace["pytest_exit_code"]
            or trace["source_python_sha256"] != compact["source_python_sha256"]):
        raise ValueError("Incomplete or mismatched pristine domain trace")
    ids = sorted(compact["tests"])
    if set(ids) - trace["tests"].keys():
        raise ValueError("Unknown tests")
    domains = sorted(trace["domains"])
    domain_ids = {domain:index for index,domain in enumerate(domains)}
    by_site = {site:{} for site in trace["sites"]}
    for index, test in enumerate(ids):
        merged = {}
        for part in (trace["tests"][test], trace["shared"].get(test.split("::")[0], {})):
            for site, pairs in part.items():
                merged.setdefault(site,set()).update(tuple(pair) for pair in pairs)
        for site, pairs in merged.items():
            for pair in pairs:
                key = str(domain_ids[pair[0]])+","+str(domain_ids[pair[1]])
                by_site[site][key] = by_site[site].get(key,0) | 1<<index
    collection_sites = sorted({site for values in trace["collection"].values() for site in values})
    compact["comparison_operand_domains"] = {
        "domains":[trace["domains"][key] for key in domains],
        "sites": {site:{pair:format(bits,"x") for pair,bits in pairs.items()} for site,pairs in by_site.items()},
        "collection_sites":collection_sites,
        "provenance":{"format":trace["format"],"tests":len(trace["tests"]),"seconds":trace["elapsed_seconds"],
                      "records":"operand types and equality slots only; no replacement outcomes"}}
    args.output.write_text(json.dumps(compact,separators=(",",":")),encoding="utf-8")
    print(json.dumps({"sites":len(by_site),"domains":len(domains),"bytes":args.output.stat().st_size}))


if __name__ == "__main__": main()
