import base64
import tempfile
import unittest
from pathlib import Path

from v2ray_subscription import build_subscription, write_subscription


class V2raySubscriptionTests(unittest.TestCase):
    def test_builds_base64_subscription_decodable_to_input_order(self):
        links = ["vless://id@a.example:443#A", "trojan://p@b.example:443#B"]

        encoded = build_subscription(links)

        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), "\n".join(links))

    def test_write_replaces_existing_file_with_complete_subscription(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "links.txt"
            output.write_text("old", encoding="utf-8")

            write_subscription(["vless://id@a.example:443#A"], output)

            self.assertNotEqual(output.read_text(encoding="utf-8"), "old")
            self.assertEqual(set(Path(directory).iterdir()), {output})
