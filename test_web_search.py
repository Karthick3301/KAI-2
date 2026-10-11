import sys
import types
import unittest
from unittest import mock

import tools


def fake_results(n, **extra):
    return [{"title": f"T{i}", "href": f"https://e.com/{i}", "body": "b" * 10, **extra} for i in range(n)]


class WebSearchTests(unittest.TestCase):
    def test_formats_results(self):
        with mock.patch.object(tools, "_search_backend", return_value=fake_results(2)):
            out = tools.web_search("hello")
        self.assertIn("untrusted content", out)
        self.assertIn("1. T0", out)
        self.assertIn("https://e.com/1", out)

    def test_count_is_clamped(self):
        calls = []
        def backend(q, n):
            calls.append(n)
            return fake_results(20)
        with mock.patch.object(tools, "_search_backend", side_effect=backend):
            out = tools.web_search("x", 100)
            tools.web_search("x", 0)
            tools.web_search("x", "bad")
        self.assertEqual(calls, [8, 5, 5])
        with mock.patch.object(tools, "_search_backend", side_effect=backend):
            tools.web_search("x", 1)
        self.assertEqual(calls[-1], 3)
        self.assertNotIn("9. ", out)

    def test_snippet_truncated(self):
        r = [{"title": "T", "href": "https://e.com", "body": "w" * 1000}]
        with mock.patch.object(tools, "_search_backend", return_value=r):
            out = tools.web_search("x")
        self.assertLess(len(out), 600)
        self.assertIn("...", out)

    def test_non_http_and_duplicates_dropped(self):
        r = [
            {"title": "A", "href": "javascript:alert(1)", "body": ""},
            {"title": "B", "href": "https://e.com", "body": ""},
            {"title": "C", "href": "https://e.com", "body": ""},
        ]
        with mock.patch.object(tools, "_search_backend", return_value=r):
            out = tools.web_search("x")
        self.assertNotIn("javascript", out)
        self.assertNotIn("C", out.split("\n", 1)[1])

    def test_empty_query_errors(self):
        with self.assertRaises(ValueError):
            tools.web_search("   ")

    def test_query_truncated(self):
        seen = []
        with mock.patch.object(tools, "_search_backend", side_effect=lambda q, n: seen.append(q) or []):
            tools.web_search("a" * 500)
        self.assertEqual(len(seen[0]), 200)

    def test_error_kinds(self):
        class RatelimitException(Exception): pass
        class TimeoutException(Exception): pass
        for exc, text in [(RatelimitException("x"), "limiting"), (TimeoutException("x"), "too long"), (RuntimeError("boom"), "not available")]:
            with mock.patch.object(tools, "_search_backend", side_effect=exc):
                with self.assertRaises(ValueError) as cm:
                    tools.web_search("x")
            self.assertIn(text, str(cm.exception))

    def test_no_results_exception(self):
        with mock.patch.object(tools, "_search_backend", side_effect=Exception("No results found.")):
            self.assertIn("No results found", tools.web_search("x"))

    def test_empty_list(self):
        with mock.patch.object(tools, "_search_backend", return_value=[]):
            self.assertIn("No usable results", tools.web_search("x"))

    def test_missing_package_message(self):
        with mock.patch.dict(sys.modules, {"ddgs": None}):
            with self.assertRaises(ValueError) as cm:
                tools.web_search("x")
        self.assertIn("pip install ddgs", str(cm.exception))

    def test_backend_calls_ddgs(self):
        fake = types.ModuleType("ddgs")
        inst = mock.Mock()
        inst.text.return_value = fake_results(1)
        fake.DDGS = mock.Mock(return_value=inst)
        with mock.patch.dict(sys.modules, {"ddgs": fake}):
            tools.web_search("cats", 3)
        fake.DDGS.assert_called_once_with(timeout=10)
        inst.text.assert_called_once_with("cats", max_results=3)

    def test_registered(self):
        tool = tools.get_tool("web_search")
        self.assertIsNotNone(tool)
        self.assertIn("query", tool.parameters)
        self.assertIn("web_search", [t.name for t in tools.get_available_tools()])


if __name__ == "__main__":
    unittest.main()
