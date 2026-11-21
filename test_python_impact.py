import tempfile
from pathlib import Path
import unittest

from python_impact import analyze, imports_safely


class ImpactTests(unittest.TestCase):
    def test_pure_comment_preserves_typed_ast(self):
        before = "from __future__ import annotations\n\ndef f(x):\n    return x + 1\n"
        self.assertEqual(analyze(before, "# extra source line\n" + before), ((), False, True))

    def test_docstring_is_executable_metadata(self):
        before = 'def f():\n    """Original"""\n    return 1\n'
        self.assertEqual(analyze(before, before.replace("Original", "Changed")), (((1, 3),), False, False))

    def test_class_rhs_and_function_body_are_distinct_impacts(self):
        before = "class A:\n    OFFSET = 1\n    def f(self):\n        return 1\n"
        self.assertEqual(analyze(before, before.replace("OFFSET = 1", "OFFSET = 2")), ((), True, False))
        self.assertEqual(analyze(before, before.replace("return 1", "return 2")), (((3, 4),), False, False))

    def test_import_definition_target_and_external_state_changes_reject(self):
        variants = [
            ("import math\n", "import os\n"),
            ("VALUE = 1\n", "OTHER = 1\n"),
            ("obj.VALUE = 1\n", "obj.VALUE = 2\n"),
            ("__all__ = ['a']\n", "__all__ = ['b']\n"),
            ("value: int\n", "value: int = 1\n"),
            ("def f(x):\n return x\n", "def f(x, y=0):\n return x\n"),
            ("def f():\n return 1\n", "def f():\n def added():\n  return 1\n return 1\n"),
        ]
        for before, after in variants:
            with self.subTest(after=after), self.assertRaises(ValueError):
                analyze(before, after)

    def test_type_comments_and_encoding_cookie_are_preserved(self):
        with self.assertRaises(ValueError):
            analyze("value = 1 # type: int\n", "value = 1 # type: str\n")
        before = "# coding: utf-8\nvalue = 'é'\n"
        self.assertEqual(analyze(before, before.replace("utf-8", "latin-1")), ((), True, False))

    def test_offline_import_sanity_accepts_valid_and_rejects_import_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "sqlglot").mkdir()
            (source / "sqlglot/__init__.py").write_text("", encoding="utf-8")
            before = "VALUE = 1\n"
            (source / "sqlglot/data.py").write_text(before, encoding="utf-8")
            self.assertTrue(imports_safely({"sqlglot/data.py": (before, "VALUE = 2\n")}, source))
            self.assertFalse(imports_safely({"sqlglot/data.py": (before, "VALUE = 1 / 0\n")}, source))


if __name__ == "__main__":
    unittest.main()
