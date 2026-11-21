"""Strict immutable Dialect-field RHS eligibility; otherwise use module masks."""

import ast


def literal_fields(before, after, allowed):
    """Return edited field names only when all remaining AST state is identical.

    `allowed` binds pristine class-qualified field names to traced consumers.
    Functions, annotations, imports, target names, field types, and other class
    statements must remain unchanged. A source hash is checked by the caller.
    """
    def normalized(text):
        tree = compile(text.encode("utf-8"), "<field-impact>", "exec",
                       ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS, dont_inherit=True)
        seen = []

        class Fields(ast.NodeTransformer):
            def __init__(self):
                self.classes = []

            def visit_ClassDef(self, node):
                self.classes.append(node.name)
                self.generic_visit(node)
                self.classes.pop()
                return node

            def visit_FunctionDef(self, node):
                return node

            visit_AsyncFunctionDef = visit_FunctionDef

            def field(self, node, target):
                key = ".".join(self.classes + [target.id])
                if self.classes and key in allowed and isinstance(node.value, ast.Constant):
                    value = node.value.value
                    if type(value) in (str, int, float, bool, type(None)):
                        seen.append((key, type(value).__name__, value))
                        node.value = ast.Constant(None)
                return node

            def visit_Assign(self, node):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    return self.field(node, node.targets[0])
                return node

            def visit_AnnAssign(self, node):
                return self.field(node, node.target) if isinstance(node.target, ast.Name) else node

        Fields().visit(tree)
        return ast.dump(tree, include_attributes=False), seen

    old_shape, old = normalized(before)
    new_shape, new = normalized(after)
    if old_shape != new_shape or len(old) != len(new):
        return None
    if any(left[:2] != right[:2] for left, right in zip(old, new)):
        return None
    changes = [left[0] for left, right in zip(old, new) if left != right]
    return changes or None
