import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from generate import parse_args, run


VALID_VLESS = (
    "vless://00000000-0000-0000-0000-000000000001@a.example:443"
    "?security=tls&sni=a.example#Node"
)


def minimal_template():
    return {
        "dns": {"servers": [{"type": "local", "tag": "local"}], "final": "local"},
        "inbounds": [{"type": "tun", "tag": "tun-in"}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"rules": [], "final": "proxy", "default_domain_resolver": "local"},
    }


class GenerateCommandTests(unittest.TestCase):
    @patch("generate.crawl_links")
    def test_crawls_once_and_writes_both_outputs(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.json"
            template.write_text(json.dumps(minimal_template()), encoding="utf-8")
            args = Namespace(
                urls=["source-a", "source-b"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=template,
                singbox_output=root / "sing-box_config.json",
                skip_singbox=False,
            )
            self.assertEqual(run(args), 0)
            crawl_links.assert_called_once_with(["source-a", "source-b"], None)
            self.assertTrue((root / "links.txt").is_file())
            self.assertTrue((root / "sing-box_config.json").is_file())
            self.assertTrue(
                (root / "sing-box_config.json").read_text(encoding="utf-8").endswith("\n")
            )

    @patch("generate.crawl_links")
    def test_conversion_failure_keeps_both_old_outputs(self, crawl_links):
        unsafe_uri = "unsupported://user:secret@example.invalid"
        crawl_links.return_value = [unsafe_uri]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            links_output = root / "links.txt"
            singbox_output = root / "sing-box_config.json"
            template = root / "template.json"
            links_output.write_text("old-links", encoding="utf-8")
            singbox_output.write_text("old-config", encoding="utf-8")
            template.write_text(json.dumps(minimal_template()), encoding="utf-8")
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=links_output,
                singbox_template=template,
                singbox_output=singbox_output,
                skip_singbox=False,
            )
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(run(args), 1)
            self.assertEqual(links_output.read_text(encoding="utf-8"), "old-links")
            self.assertEqual(singbox_output.read_text(encoding="utf-8"), "old-config")
            self.assertNotIn(unsafe_uri, stderr.getvalue())
            self.assertNotIn("secret", stderr.getvalue())

    @patch("generate.crawl_links")
    def test_skip_singbox_only_writes_v2ray_output(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=root / "missing-template.json",
                singbox_output=root / "sing-box_config.json",
                skip_singbox=True,
            )
            self.assertEqual(run(args), 0)
            self.assertTrue((root / "links.txt").is_file())
            self.assertFalse((root / "sing-box_config.json").exists())

    def test_cli_keeps_url_aliases_and_output_defaults(self):
        for alias in ("-u", "--url", "--urls"):
            with self.subTest(alias=alias), patch(
                "sys.argv", ["generate.py", alias, "source-a", "source-b"]
            ):
                args = parse_args()
                self.assertEqual(args.urls, ["source-a", "source-b"])
                self.assertEqual(args.output_file, "links.txt")
                self.assertEqual(args.singbox_template, "sing-box_template.json")
                self.assertEqual(args.singbox_output, "sing-box_config.json")
                self.assertFalse(args.skip_singbox)

    @patch("generate.crawl_links")
    def test_unexpected_subscription_value_error_remains_visible(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=root / "unused-template.json",
                singbox_output=root / "sing-box_config.json",
                skip_singbox=True,
            )
            with patch(
                "generate.build_subscription",
                side_effect=ValueError("unexpected subscription failure"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "unexpected subscription failure"
                ):
                    run(args)

    @patch("generate.crawl_links")
    def test_unexpected_singbox_builder_os_error_remains_visible(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.json"
            template.write_text(json.dumps(minimal_template()), encoding="utf-8")
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=template,
                singbox_output=root / "sing-box_config.json",
                skip_singbox=False,
            )
            with patch(
                "generate.build_singbox_config",
                side_effect=OSError("unexpected builder failure"),
            ):
                with self.assertRaisesRegex(OSError, "unexpected builder failure"):
                    run(args)

    @patch("generate.crawl_links")
    def test_unexpected_writer_os_error_remains_visible(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=root / "unused-template.json",
                singbox_output=root / "sing-box_config.json",
                skip_singbox=True,
            )
            with patch(
                "generate.atomic_write_text",
                side_effect=OSError("unexpected writer failure"),
            ):
                with self.assertRaisesRegex(OSError, "unexpected writer failure"):
                    run(args)

    @patch("generate.crawl_links")
    def test_missing_template_is_a_safe_known_failure(self, crawl_links):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=root / "links.txt",
                singbox_template=root / "missing-template.json",
                singbox_output=root / "sing-box_config.json",
                skip_singbox=False,
            )
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(run(args), 1)
            self.assertIn("Generation failed", stderr.getvalue())
            self.assertNotIn(VALID_VLESS, stderr.getvalue())

    @patch("generate.crawl_links")
    def test_rejects_normalized_output_path_collisions_before_crawling(
        self, crawl_links
    ):
        crawl_links.return_value = [VALID_VLESS]
        collision_builders = {
            "v2ray output and template": lambda root: (
                root / "nested" / ".." / "template.json",
                root / "template.json",
                root / "sing-box.json",
            ),
            "v2ray and sing-box outputs": lambda root: (
                root / "links.txt",
                root / "template.json",
                root / "nested" / ".." / "links.txt",
            ),
            "sing-box output and template": lambda root: (
                root / "links.txt",
                root / "template.json",
                root / "nested" / ".." / "template.json",
            ),
        }

        for label, build_paths in collision_builders.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "nested").mkdir()
                output, template, singbox_output = build_paths(root)
                template.write_text(json.dumps(minimal_template()), encoding="utf-8")
                args = Namespace(
                    urls=["https://source.example/nodes"],
                    additional_regex=None,
                    output_file=output,
                    singbox_template=template,
                    singbox_output=singbox_output,
                    skip_singbox=False,
                )

                stderr = StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(run(args), 1)
                self.assertIn("different paths", stderr.getvalue())

        crawl_links.assert_not_called()

    @patch("generate.crawl_links")
    def test_skip_singbox_allows_collisions_with_unused_singbox_paths(
        self, crawl_links
    ):
        crawl_links.return_value = [VALID_VLESS]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "links.txt"
            args = Namespace(
                urls=["source"],
                additional_regex=None,
                output_file=output,
                singbox_template=output,
                singbox_output=output,
                skip_singbox=True,
            )

            self.assertEqual(run(args), 0)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
