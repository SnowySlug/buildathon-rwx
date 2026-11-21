import unittest

from field_impact import literal_fields


class FieldGuardTests(unittest.TestCase):
    before = "class Demo:\n    FLAG = 1\n    OTHER = False\n    def f(self):\n        return self.FLAG\n"
    allowed = {"Demo.FLAG": "1", "Demo.OTHER": "2"}

    def test_literal_same_type_only(self):
        self.assertEqual(literal_fields(self.before, self.before.replace("FLAG = 1", "FLAG = 4"), self.allowed), ["Demo.FLAG"])
        for value in ("True", "'4'", "[4]", "int('4')"):
            with self.subTest(value=value):
                self.assertIsNone(literal_fields(self.before, self.before.replace("FLAG = 1", "FLAG = " + value), self.allowed))

    def test_preserve_all_other_code(self):
        for after in (self.before.replace("self.FLAG", "self.OTHER"),
                      self.before.replace("FLAG = 1", "RENAMED = 1"),
                      "import os\n" + self.before,
                      self.before.replace("FLAG = 1", "FLAG: int = 4")):
            with self.subTest(after=after):
                self.assertIsNone(literal_fields(self.before, after, self.allowed))

    def test_unknown_fields_and_function_locals(self):
        self.assertIsNone(literal_fields(self.before, self.before.replace("FLAG = 1", "FLAG = 4"), {}))
        before = "class Demo:\n    def f(self):\n        FLAG = 1\n        return FLAG\n"
        self.assertIsNone(literal_fields(before, before.replace("FLAG = 1", "FLAG = 4"), self.allowed))

    def test_multiple_fields_union(self):
        after = self.before.replace("FLAG = 1", "FLAG = 4").replace("OTHER = False", "OTHER = True")
        self.assertEqual(literal_fields(self.before, after, self.allowed), ["Demo.FLAG", "Demo.OTHER"])

    def test_signed_numeric_literals(self):
        before = self.before.replace("FLAG = 1", "FLAG = -1")
        self.assertEqual(literal_fields(before, before.replace("FLAG = -1", "FLAG = -3"), self.allowed), ["Demo.FLAG"])
        self.assertIsNone(literal_fields(before, before.replace("FLAG = -1", "FLAG = -(1 + 2)"), self.allowed))


if __name__ == "__main__":
    unittest.main()
