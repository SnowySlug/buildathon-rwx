import unittest
from enum import Enum

from semantic_impact import changed_comparisons, domains_prove
from trace_comparison_types import Profile


class DomainProofTests(unittest.TestCase):
    def test_canonical_string_enum(self):
        class Mode(str, Enum):
            A = "a"
            B = "b"
        p = Profile()
        a, b = p.domain(Mode.A), p.domain(Mode.B)
        self.assertTrue(domains_prove(p.domains[a], p.domains[b]))
        text = p.domain("a")
        self.assertFalse(domains_prove(p.domains[a], p.domains[text]))
        for left in Mode:
            for right in Mode:
                self.assertEqual(left is right, left == right)

    def test_identity_object_and_overloaded_equality(self):
        class Plain: pass
        class Overloaded:
            def __eq__(self, other): return True
        p = Profile()
        none, plain, overloaded = map(p.domain, (None, Plain(), Overloaded()))
        self.assertTrue(domains_prove(p.domains[none], p.domains[plain]))
        self.assertFalse(domains_prove(p.domains[none], p.domains[overloaded]))
        self.assertTrue(Overloaded() == None)

    def test_recreated_same_qualname_enums_are_distinct(self):
        def make():
            class Mode(str, Enum):
                A = "a"
            return Mode
        first, second = make(), make()
        self.assertEqual(first.__qualname__, second.__qualname__)
        self.assertTrue(first.A == second.A)
        self.assertFalse(first.A is second.A)
        p = Profile()
        left, right = p.domain(first.A), p.domain(second.A)
        self.assertFalse(domains_prove(p.domains[left], p.domains[right]))

    def test_operator_only_ast_guard(self):
        self.assertEqual(changed_comparisons("x = a is b", "x = a == b"), ["1:4"])
        self.assertEqual(changed_comparisons("x = a is not b", "x = a != b"), ["1:4"])
        for after in ("x = a == c", "x = a != b", "x = a == b\ny = 1", "x = a is b"):
            with self.subTest(after=after):
                self.assertIsNone(changed_comparisons("x = a is b", after))

    def test_any_unknown_domain_retains_entire_patch_selection(self):
        from selector import select
        before = "def f(a, b):\n    return a is b\n"
        tests = [{"id": label, "number": i, "file": "test.py", "seconds": 1}
                 for i, label in enumerate(("a", "b"))]
        coverage = {"tests": {label: {"lines": {"p.py": [1]}, "opened": []}
                              for label in ("a", "b")},
            "comparison_operand_domains": {"domains": [
                {"kind": "none", "type": "None"},
                {"kind": "object_identity", "type": "Plain"},
                {"kind": "unknown", "type": "Overloaded"}],
                "sites": {"p.py:2:11": {"0,1": "1", "0,2": "2"}},
                "collection_sites": []}}
        selected, _ = select(tests, {"p.py": (before, before.replace(" is ", " == "))}, coverage)
        self.assertEqual([test["id"] for test in selected], ["a", "b"])


if __name__ == "__main__": unittest.main()
