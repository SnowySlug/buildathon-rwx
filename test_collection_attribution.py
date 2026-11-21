import ast
import sys
import unittest

from repair_collection_map import attribute_collection_event


class CollectionAttributionTests(unittest.TestCase):
    SOURCE = "def f(\n    x: int = 1,\n    flag: bool = False,\n) -> int:\n    value = x + 1\n    return value\n"

    def record(self, call):
        observed = set()
        filename = "<collection-attribution-proof>"

        def trace(frame, event, arg):
            if event == "line" and frame.f_code.co_filename == filename:
                observed.add(frame.f_lineno)
            return trace

        namespace = {}
        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            exec(compile(self.SOURCE, filename, "exec"), namespace)
            if call:
                namespace["f"]()
        finally:
            sys.settrace(previous)
        return sorted(observed)

    def test_real_signature_annotation_events_do_not_mean_body_executed(self):
        node = ast.parse(self.SOURCE).body[0]
        observed = self.record(False)
        self.assertTrue(observed)
        witness, ambiguous, body_start = attribute_collection_event(node, observed)
        self.assertEqual(body_start, 5)
        self.assertIsNone(witness)
        self.assertFalse(ambiguous)

    def test_real_body_call_is_preserved(self):
        node = ast.parse(self.SOURCE).body[0]
        witness, ambiguous, body_start = attribute_collection_event(node, self.record(True))
        self.assertIsNotNone(witness)
        self.assertGreaterEqual(witness, body_start)
        self.assertFalse(ambiguous)

    def test_one_line_generator_async_and_doc_only_are_conservative(self):
        for source in ("def f(): return 1\n", "def f():\n    yield 1\n",
                       "async def f():\n    return 1\n", 'def f():\n    """Docs"""\n'):
            with self.subTest(source=source):
                node = ast.parse(source).body[0]
                witness, ambiguous, _ = attribute_collection_event(node, [node.lineno])
                self.assertEqual(witness, node.lineno)
                self.assertTrue(ambiguous)


if __name__ == "__main__":
    unittest.main()
