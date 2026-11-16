import re
import unittest
from contextlib import redirect_stderr
from io import StringIO
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

        with patch("crawler.requests.get", return_value=Response()):
            with redirect_stderr(StringIO()):
                with self.assertRaises(NoLinksError):
                    crawl_links(["unavailable"])


class CloudflareEmailTests(unittest.TestCase):
    @staticmethod
    def encode_cf_email(plain: str) -> str:
        key = 0x7A
        return (bytes([key]) + bytes(b ^ key for b in plain.encode())).hex()

    def test_cf_email_decode_keeps_uri_in_one_line(self):
        encoded = self.encode_cf_email("dongtaiwang.com@ip5.934618.xyz")
        page = (
            f'<div>anytls://<a class="__cf_email__" data-cfemail="{encoded}">'
            f"[email&#160;protected]</a>:23550?security=tls&amp;sn=host#node</div>"
        )

        class Response:
            text = page

            def raise_for_status(self):
                return None

        with patch("crawler.requests.get", return_value=Response()):
            links = crawl_links(["https://source.example/nodes"])

        self.assertEqual(
            links,
            [
                "anytls://dongtaiwang.com@ip5.934618.xyz"
                ":23550?security=tls&sn=host#node"
            ],
        )

    def test_links_separated_by_heavy_markup_are_not_merged(self):
        page = (
            "<div><p>标题段落</p><span>说明文字</span>"
            "<table><tr><td>vmess://AAA</td></tr></table>"
            "<p>中间还有很多无关内容 abc def ghi</p><ul><li>注释</li></ul>"
            "<div><span>vless://BBB</span></div></div>"
        )

        class Response:
            text = page

            def raise_for_status(self):
                return None

        with patch("crawler.requests.get", return_value=Response()):
            links = crawl_links(["https://source.example/nodes"])

        self.assertEqual(links, ["vmess://AAA", "vless://BBB"])

    def test_malformed_cf_email_does_not_drop_other_links(self):
        page = (
            '<div>vmess://AAA<a class="__cf_email__" data-cfemail="abc">x</a>'
            "vless://BBB</div>"
        )

        class Response:
            text = page

            def raise_for_status(self):
                return None

        with redirect_stderr(StringIO()):
            with patch("crawler.requests.get", return_value=Response()):
                links = crawl_links(["https://source.example/nodes"])

        self.assertEqual(links, ["vmess://AAA", "vless://BBB"])
