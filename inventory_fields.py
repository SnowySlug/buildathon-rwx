"""Inventory a strict subset for field-level dependency research, never selection.

Reports candidates; it does not establish soundness or omit any test.
Only immutable literal class fields whose every statically known owner descends
from Dialect qualify. Derived/module-time reads, writes outside declarations,
field names appearing as runtime strings, and unresolved owner classes reject.
"""

import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path


def inventory(source):
    classes = {}
    fields = defaultdict(list)
    occurrences = defaultdict(list)
    strings = defaultdict(list)
    bare_reads = defaultdict(list)
    paths = sorted(path for root in ("sqlglot", "tests") for path in (source / root).rglob("*.py"))
    for path in paths:
        name = path.relative_to(source).as_posix()
        module = name[:-3].replace("/", ".").removesuffix(".__init__")
        tree = ast.parse(path.read_text("utf-8"))
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                aliases.update({a.asname or a.name: node.module + "." + a.name for a in node.names})
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

        def scope(node):
            output = []
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    output.append(node)
            return output

        def resolve(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, module + "." + node.id)
            if isinstance(node, ast.Attribute):
                return resolve(node.value) + "." + node.attr
            return "<unknown>"

        for node in ast.walk(tree):
            scopes = scope(node)
            if isinstance(node, ast.ClassDef):
                qualified = module + "." + ".".join([n.name for n in reversed(scopes) if isinstance(n, ast.ClassDef)] + [node.name])
                classes[qualified] = [resolve(base) for base in node.bases]
                for statement in node.body:
                    targets = (statement.targets if isinstance(statement, ast.Assign)
                               else [statement.target] if isinstance(statement, ast.AnnAssign) else [])
                    for target in targets:
                        if isinstance(target, ast.Name):
                            value = statement.value
                            literal = isinstance(value, ast.Constant) and type(value.value) in (str, int, float, bool, type(None))
                            if (isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub))
                                    and isinstance(value.operand, ast.Constant)
                                    and type(value.operand.value) in (int, float)):
                                literal = True
                            fields[target.id].append({"owner": qualified, "path": name,
                                                      "line": target.lineno, "literal": literal})
            if isinstance(node, ast.Attribute):
                functions = [n for n in scopes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                occurrences[node.attr].append({"path": name, "line": node.lineno,
                    "write": not isinstance(node.ctx, ast.Load),
                    "derived": not functions or functions[0].name in ("__new__", "__init_subclass__")})
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.isidentifier():
                    strings[node.value].append({"path": name, "line": node.lineno})
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                bare_reads[node.id].append({"path": name, "line": node.lineno})

    def dialect_owner(name, seen=frozenset()):
        if name == "sqlglot.dialects.dialect.Dialect":
            return True
        if name in seen:
            return False
        return any(dialect_owner(base, seen | {name}) for base in classes.get(name, []))

    candidates = {}
    for field, owners in sorted(fields.items()):
        if field.startswith("_") or not all(item["literal"] and dialect_owner(item["owner"]) for item in owners):
            continue
        refs = occurrences[field]
        if strings[field] or bare_reads[field] or any(item["write"] or item["derived"] for item in refs):
            continue
        candidates[field] = {"owners": owners, "reads": refs}
    return {"note": "Research inventory only; not a soundness proof or selector.",
            "classes": len(classes), "candidate_fields": candidates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.source)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"classes": result["classes"], "candidate_fields": list(result["candidate_fields"])}))
