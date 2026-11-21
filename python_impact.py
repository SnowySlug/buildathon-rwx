"""Structural Python impact analysis and bounded offline import validation."""

import ast
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import sys


@lru_cache(maxsize=128)
def analyze(before, after):
    def parse(source):
        return compile(source.encode("utf-8"), "<pristine-impact>", "exec",
                       ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS, dont_inherit=True)

    old_tree, new_tree = parse(before), parse(after)
    if ast.dump(old_tree, include_attributes=False) == ast.dump(new_tree, include_attributes=False):
        return (), False, True

    def definitions(tree):
        output = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                try:
                    node.body = [ast.Pass()]
                    output.append(ast.dump(node, include_attributes=False))
                finally:
                    node.body = body
            elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                output.append(ast.dump(node, include_attributes=False))
        return output

    if definitions(old_tree) != definitions(new_tree):
        raise ValueError("definitions or imports changed")

    class Skeleton(ast.NodeTransformer):
        def __init__(self):
            self.functions = []
            self.data = []

        def visit_FunctionDef(self, node):
            self.functions.append((ast.dump(node, include_attributes=False), node.lineno, node.end_lineno))
            node.body = [ast.Pass()]
            return node

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Assign(self, node):
            if any(not isinstance(target, ast.Name) or target.id.startswith("__") for target in node.targets):
                return node
            self.data.append(ast.dump(node.value, include_attributes=False))
            node.value = ast.Constant(None)
            return node

        def visit_AnnAssign(self, node):
            if not isinstance(node.target, ast.Name) or node.target.id.startswith("__"):
                return node
            if node.value is None:
                self.data.append(None)
                return node
            self.data.append(ast.dump(node.value, include_attributes=False) if node.value else None)
            node.value = ast.Constant(None)
            return node

    old, new = Skeleton(), Skeleton()
    old_shape = ast.dump(old.visit(old_tree), include_attributes=False)
    new_shape = ast.dump(new.visit(new_tree), include_attributes=False)
    if old_shape != new_shape or len(old.functions) != len(new.functions) or len(old.data) != len(new.data):
        raise ValueError("unsupported module structure change")
    spans = tuple((left[1], left[2]) for left, right in zip(old.functions, new.functions) if left[0] != right[0])
    return spans, old.data != new.data, False


IMPORT_CHECK = r'''
import importlib, importlib.abc, importlib.util, json, pathlib, sys
request = json.load(sys.stdin)
source = pathlib.Path(request["source"])
patches = request["patches"]
modules = {}
for name in patches:
    pieces = pathlib.PurePosixPath(name).parts
    if pieces[0] not in ("sqlglot", "tests"):
        raise RuntimeError("unsupported import root")
    module = name[:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module[:-9]
    modules[module] = name
class Loader(importlib.abc.Loader):
    def __init__(self, name): self.name = name
    def create_module(self, spec): return None
    def exec_module(self, module):
        name = self.name
        exec(compile(patches[name].encode("utf-8"), str(source / name), "exec"), module.__dict__)
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        name = modules.get(fullname)
        if name is None: return None
        filename = source / name
        return importlib.util.spec_from_file_location(fullname, filename, loader=Loader(name),
            submodule_search_locations=[str(filename.parent)] if name.endswith("/__init__.py") else None)
sys.path.insert(0, str(source))
sys.meta_path.insert(0, Finder())
for name in sorted(modules, key=lambda value: (value.count("."), value)):
    importlib.import_module(name)
'''


def imports_safely(edits, source):
    payload = {"source": str(source), "patches": {name: texts[1] for name, texts in edits.items() if name.endswith(".py")}}
    try:
        result = subprocess.run([sys.executable, "-c", IMPORT_CHECK], input=json.dumps(payload).encode("utf-8"),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.5)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
