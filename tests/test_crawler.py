import re
import unittest
from contextlib import redirect_stderr
from io import StringIO
from types import ModuleType
from unittest.mock import patch

from crawler import NoLinksError, crawl_links, extract_links


class ExtractLinksTests(unittest.TestCase):
    def test_extracts_links_at_text_boundaries_and_deduplicates_in_order(self):
        text = (
            "vless://id@a.example:443#first\n"
            "paragraph vmess://dm1lc3M=\n"
            "vless://id@a.example:443#first\n"
            "ss://YWVzLTEyOC1nY206cGFzcw==@b.example:8388#last"
        )

        self.assertEqual(
            extract_links(text),
            [
                "vless://id@a.example:443#first",
                "vmess://dm1lc3M=",
                "ss://YWVzLTEyOC1nY206cGFzcw==@b.example:8388#last",
            ],
        )

    def test_additional_regex_with_one_capture_group_returns_full_match(self):
        self.assertEqual(
            extract_links(
                "custom://node.example/path",
                r"custom://(node\.[^/\s]+/\w+)",
            ),
            ["custom://node.example/path"],
        )

    def test_additional_regex_with_multiple_capture_groups_returns_full_match(self):
        self.assertEqual(
            extract_links(
                "custom://node.example/path",
                r"(custom)://([^/\s]+/\w+)",
            ),
            ["custom://node.example/path"],
        )

    def test_invalid_additional_regex_is_visible_before_fetching_sources(self):
        fetched = []

        with self.assertRaises(re.error):
            crawl_links(
                ["https://user:secret@source.example/private?token=credential"],
                additional_regex="(",
                fetcher=lambda url: fetched.append(url) or "",
            )

        self.assertEqual(fetched, [])

    def test_crawl_keeps_successes_when_one_source_fails(self):
        pages = {
            "good": "trojan://secret@node.example:443#node",
            "bad": RuntimeError("offline"),
        }

        def fetch(url):
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        with redirect_stderr(StringIO()):
            links = crawl_links(["bad", "good"], fetcher=fetch)

        self.assertEqual(links, ["trojan://secret@node.example:443#node"])

    def test_partial_source_failure_reports_only_index_and_sanitized_hostname(self):
        failing_source = (
            "https://user:password@source.example/private?token=credential"
        )
        successful_source = "https://good.example/nodes"

        def fetch(url):
            if url == failing_source:
                raise RuntimeError("response included trojan://private-credential")
            return "vless://id@node.example:443#node"

        stderr = StringIO()
        with redirect_stderr(stderr):
            links = crawl_links([failing_source, successful_source], fetcher=fetch)

        message = stderr.getvalue()
        self.assertEqual(links, ["vless://id@node.example:443#node"])
        self.assertIn("Source 1", message)
        self.assertIn("source.example", message)
        for secret in ("user", "password", "private", "token", "credential"):
            self.assertNotIn(secret, message)

    def test_source_keyboard_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            crawl_links(
                ["https://source.example/nodes"],
                fetcher=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
            )

    def test_crawl_raises_when_all_sources_fail_or_are_empty(self):
        with self.assertRaises(NoLinksError):
            crawl_links(["empty"], fetcher=lambda _: "no proxy links")

    def test_default_fetcher_rejects_http_error_responses(self):
        class Response:
            text = "trojan://secret@node.example:443#node"

            def raise_for_status(self):
                raise RuntimeError("HTTP 503")

        requests = ModuleType("requests")
        requests.get = lambda url, timeout: Response()
        bs4 = ModuleType("bs4")

        class Soup:
            def __init__(self, text, parser):
                self.text = text

            def get_text(self, separator):
                return self.text

        bs4.BeautifulSoup = Soup

        with patch.dict("sys.modules", {"requests": requests, "bs4": bs4}):
            with redirect_stderr(StringIO()):
                with self.assertRaises(NoLinksError):
                    crawl_links(["unavailable"])
