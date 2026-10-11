"""web_fetch must only reach public websites, even through redirects."""
import unittest
from unittest import mock

import requests
import tools

PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")

    def close(self):
        pass


def fetch(url):
    return tools.execute_tool("web_fetch", {"url": url})


class BlockedAddressTests(unittest.TestCase):
    def test_private_and_internal_addresses_are_blocked(self):
        urls = [
            "http://localhost/",
            "http://localhost:8000/secret",
            "http://127.0.0.1/",
            "http://0.0.0.0/",
            "http://10.0.0.5/",
            "http://192.168.1.1/admin",
            "http://172.16.0.9/",
            "http://169.254.169.254/latest/meta-data",   # cloud secrets address
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://user@127.0.0.1/",
        ]
        for url in urls:
            with mock.patch.object(tools.requests, "get", side_effect=AssertionError("must not connect")):
                result = fetch(url)
            self.assertTrue(result.startswith("Error:"), (url, result))
            self.assertIn("Blocked", result, url)

    def test_other_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"):
            self.assertTrue(fetch(url).startswith("Error:"), url)


class RedirectTests(unittest.TestCase):
    def resolver(self, host):
        return ["127.0.0.1"] if host == "127.0.0.1" else [PUBLIC_IP]

    def test_redirect_to_private_address_is_blocked(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            self.assertFalse(kwargs.get("allow_redirects", True), "redirects must be checked by us")
            return FakeResponse(302, headers={"Location": "http://127.0.0.1/admin"})

        with mock.patch.object(tools, "_resolve_ips", self.resolver), \
                mock.patch.object(tools.requests, "get", fake_get):
            result = fetch("http://example.com/start")
        self.assertTrue(result.startswith("Error:"), result)
        self.assertIn("Blocked", result)
        self.assertEqual(calls, ["http://example.com/start"])   # never touched the private address

    def test_redirect_loop_stops(self):
        def fake_get(url, **kwargs):
            return FakeResponse(302, headers={"Location": "/again"})

        with mock.patch.object(tools, "_resolve_ips", self.resolver), \
                mock.patch.object(tools.requests, "get", fake_get):
            result = fetch("http://example.com/loop")
        self.assertIn("Too many redirects", result)

    def test_normal_redirect_is_followed(self):
        def fake_get(url, **kwargs):
            if url.endswith("/old"):
                return FakeResponse(301, headers={"Location": "/new"})
            return FakeResponse(200, b"final page")

        with mock.patch.object(tools, "_resolve_ips", self.resolver), \
                mock.patch.object(tools.requests, "get", fake_get):
            result = fetch("http://example.com/old")
        self.assertIn("final page", result)
        self.assertIn("http://example.com/new", result)


class NormalFetchTests(unittest.TestCase):
    def run_fetch(self, body, headers=None):
        with mock.patch.object(tools, "_resolve_ips", lambda host: [PUBLIC_IP]), \
                mock.patch.object(tools.requests, "get", lambda url, **kw: FakeResponse(200, body, headers)):
            return fetch("http://example.com/")

    def test_public_page_works_and_is_labelled_untrusted(self):
        result = self.run_fetch("hello 25 × 4 😊".encode("utf-8"))
        self.assertIn("hello 25 × 4 😊", result)
        self.assertIn("untrusted", result)

    def test_huge_page_is_cut_short(self):
        result = self.run_fetch(b"a" * 5_000_000)
        self.assertLess(len(result), tools.WEB_FETCH_MAX_CHARS + 300)
        self.assertIn("truncated", result)

    def test_declared_charset_is_respected(self):
        result = self.run_fetch("café".encode("latin-1"), {"Content-Type": "text/html; charset=latin-1"})
        self.assertIn("café", result)

    def test_http_error_is_reported(self):
        with mock.patch.object(tools, "_resolve_ips", lambda host: [PUBLIC_IP]), \
                mock.patch.object(tools.requests, "get", lambda url, **kw: FakeResponse(404)):
            self.assertTrue(fetch("http://example.com/missing").startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
