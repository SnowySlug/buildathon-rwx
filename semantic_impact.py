"""Conservative proofs for operator-only identity/equality comparison edits."""

import ast


def changed_comparisons(before, after):
    def normalize(text):
        tree = compile(text.encode("utf-8"), "<comparison-impact>", "exec",
                       ast.PyCF_ONLY_AST | ast.PyCF_TYPE_COMMENTS, dont_inherit=True)
        sites = []
        class Comparisons(ast.NodeTransformer):
            def visit_Compare(self, node):
                self.generic_visit(node)
                if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.Eq, ast.IsNot, ast.NotEq)):
                    sites.append((node.lineno, node.col_offset, type(node.ops[0]).__name__))
                    node.ops[0] = ast.IsNot() if isinstance(node.ops[0], (ast.IsNot, ast.NotEq)) else ast.Is()
                return node
        Comparisons().visit(tree)
        return ast.dump(tree, include_attributes=False), sites
    old_shape, old = normalize(before)
    new_shape, new = normalize(after)
    if old_shape != new_shape or len(old) != len(new):
        return None
    output = []
    for left, right in zip(old, new):
        if left[2] != right[2]:
            if (left[2], right[2]) not in (("Is", "Eq"), ("IsNot", "NotEq")):
                return None
            output.append(str(left[0]) + ":" + str(left[1]))
    return output or None


def domains_prove(left, right):
    """Use type/slot facts, never precomputed replacement-operator outcomes."""
    a, b = left["kind"], right["kind"]
    if a == "none" and b in ("none", "object_identity"):
        return True
    if b == "none" and a in ("none", "object_identity"):
        return True
    if a == b == "object_identity":
        return True
    return (a == b and a in ("canonical_str_enum", "canonical_int_enum")
            and "class_id" in left and "class_id" in right
            and left["class_id"] == right["class_id"])
