import copy
import unittest

from merge_attributes import merge


class AttributeMapGuards(unittest.TestCase):
    def setUp(self):
        self.compact = {"tests": {"a": {}, "b": {}}, "source_python_sha256": {"p": "hash"}}
        self.trace = {"pytest_exit_code": 0, "failed": [], "collection_errors": [], "missing": [],
            "source_python_sha256": {"p": "hash"}, "format": "test", "elapsed_seconds": 1,
            "collection": {}, "tests": {"a": ["p.py::__dict__"], "b": ["p.py::FLAG"]}}
        self.inventory = {"candidate_fields": {"FLAG": {"owners": [
            {"path": "p.py", "owner": "p.Dialect"}]}}}

    def test_namespace_reads_are_field_consumers(self):
        merged = merge(self.compact, self.trace, self.inventory)
        self.assertEqual(merged["dialect_literal_field_bits"]["p.py"]["Dialect.FLAG"], "3")

    def test_collection_read_retains_module_fallback(self):
        self.trace["collection"] = {"test.py": ["p.py::FLAG"]}
        self.assertEqual(merge(self.compact, self.trace, self.inventory)["dialect_literal_field_bits"], {})

    def test_failing_incomplete_and_mismatched_trace_rejected(self):
        for changed in ({"failed": ["a"]}, {"missing": ["a"]},
                        {"source_python_sha256": {"p": "wrong"}}, {"pytest_exit_code": 2}):
            with self.subTest(changed=changed):
                trace = copy.deepcopy(self.trace)
                trace.update(changed)
                with self.assertRaises(ValueError):
                    merge(copy.deepcopy(self.compact), trace, self.inventory)


if __name__ == "__main__":
    unittest.main()
