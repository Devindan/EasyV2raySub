import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from singbox_convertor import (
    NoValidOutboundsError,
    ParsedOutbound,
    build_singbox_config,
    parse_proxy_uri,
    write_singbox_config,
)


VALID_VLESS = (
    "vless://00000000-0000-0000-0000-000000000001@a.example:443"
    "?security=tls&sni=a.example#Node"
)


def minimal_template():
    return {
        "dns": {"servers": [{"type": "local", "tag": "local"}], "final": "local"},
        "inbounds": [{"type": "tun", "tag": "tun-in"}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {
            "rules": [],
            "final": "proxy",
            "default_domain_resolver": "local",
        },
    }


class ProxyUriParserTests(unittest.TestCase):
    def test_parses_supported_protocols(self):
        cases = {
            (
                "vless://00000000-0000-0000-0000-000000000001@v.example:443"
                "?security=reality&type=grpc&sni=www.example.com&pbk=public&sid=abcd"
                "&serviceName=svc#VLESS"
            ): {
                "type": "vless",
                "server": "v.example",
                "server_port": 443,
                "uuid": "00000000-0000-0000-0000-000000000001",
                "transport": {"type": "grpc", "service_name": "svc"},
                "tls": {
                    "enabled": True,
                    "server_name": "www.example.com",
                    "reality": {
                        "enabled": True,
                        "public_key": "public",
                        "short_id": "abcd",
                    },
                },
            },
            (
                "trojan://password@t.example:443?security=tls&sni=t.example"
                "&type=ws&path=%2Fws#Trojan"
            ): {
                "type": "trojan",
                "server": "t.example",
                "server_port": 443,
                "password": "password",
                "transport": {"type": "ws", "path": "/ws"},
                "tls": {"enabled": True, "server_name": "t.example"},
            },
            "ss://YWVzLTEyOC1nY206cGFzcw==@s.example:8388#SS": {
                "type": "shadowsocks",
                "server": "s.example",
                "server_port": 8388,
                "method": "aes-128-gcm",
                "password": "pass",
            },
            (
                "hysteria2://password@h.example:443?sni=h.example&insecure=1"
                "&obfs=salamander&obfs-password=obfs#HY2"
            ): {
                "type": "hysteria2",
                "server": "h.example",
                "server_port": 443,
                "password": "password",
                "obfs": {"type": "salamander", "password": "obfs"},
                "tls": {
                    "enabled": True,
                    "server_name": "h.example",
                    "insecure": True,
                },
            },
            (
                "tuic://00000000-0000-0000-0000-000000000001:password@u.example:443"
                "?sni=u.example&congestion_control=bbr#TUIC"
            ): {
                "type": "tuic",
                "server": "u.example",
                "server_port": 443,
                "uuid": "00000000-0000-0000-0000-000000000001",
                "password": "password",
                "congestion_control": "bbr",
                "tls": {"enabled": True, "server_name": "u.example"},
            },
            "anytls://password@a.example:443?sni=a.example&insecure=1#AnyTLS": {
                "type": "anytls",
                "server": "a.example",
                "server_port": 443,
                "password": "password",
                "tls": {
                    "enabled": True,
                    "server_name": "a.example",
                    "insecure": True,
                },
            },
        }

        for uri, expected_outbound in cases.items():
            with self.subTest(expected_outbound["type"]):
                parsed = parse_proxy_uri(uri)
                self.assertIsInstance(parsed, ParsedOutbound)
                self.assertEqual(parsed.outbound, expected_outbound)

    def test_vless_preserves_reality_grpc_and_utls_fields(self):
        parsed = parse_proxy_uri(
            "vless://00000000-0000-0000-0000-000000000001@v.example:443"
            "?security=reality&type=grpc&sni=www.example.com&pbk=public&sid=abcd"
            "&serviceName=svc&fp=chrome#VLESS"
        )

        self.assertEqual(
            parsed.outbound["transport"], {"type": "grpc", "service_name": "svc"}
        )
        self.assertEqual(
            parsed.outbound["tls"]["reality"],
            {"enabled": True, "public_key": "public", "short_id": "abcd"},
        )
        self.assertEqual(
            parsed.outbound["tls"]["utls"],
            {"enabled": True, "fingerprint": "chrome"},
        )

    def test_parses_vmess_json_with_ws_and_tls(self):
        payload = base64.b64encode(
            json.dumps(
                {
                    "v": "2",
                    "ps": "VMess",
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "aid": "0",
                    "scy": "auto",
                    "net": "ws",
                    "path": "/ws",
                    "host": "cdn.example",
                    "tls": "tls",
                    "sni": "m.example",
                }
            ).encode("utf-8")
        ).decode("ascii")

        parsed = parse_proxy_uri(f"vmess://{payload}")

        self.assertEqual(parsed.display_name, "VMess")
        self.assertEqual(parsed.outbound["type"], "vmess")
        self.assertEqual(parsed.outbound["server"], "m.example")
        self.assertEqual(parsed.outbound["server_port"], 443)
        self.assertEqual(
            parsed.outbound["transport"],
            {"type": "ws", "path": "/ws", "headers": {"Host": "cdn.example"}},
        )
        self.assertEqual(
            parsed.outbound["tls"], {"enabled": True, "server_name": "m.example"}
        )

    def test_maps_http_and_httpupgrade_transports(self):
        cases = {
            (
                "vless://00000000-0000-0000-0000-000000000001@v.example:80"
                "?type=http&host=one.example%2Ctwo.example&path=%2Fhttp#HTTP"
            ): {
                "type": "http",
                "host": ["one.example", "two.example"],
                "path": "/http",
            },
            (
                "trojan://password@t.example:443?security=tls&type=httpupgrade"
                "&host=cdn.example&path=%2Fupgrade#Upgrade"
            ): {"type": "httpupgrade", "host": "cdn.example", "path": "/upgrade"},
        }

        for uri, expected_transport in cases.items():
            with self.subTest(expected_transport["type"]):
                parsed = parse_proxy_uri(uri)
                self.assertEqual(parsed.outbound["transport"], expected_transport)

    def test_supports_hy2_alias_allow_insecure_and_urlsafe_base64(self):
        hy2 = parse_proxy_uri(
            "hy2://password@h.example:443?sni=h.example&allowInsecure=true#HY2"
        )
        shadowsocks = parse_proxy_uri(
            "ss://YWVzLTEyOC1nY206w7_Dvw@s.example:8388#URLSafe"
        )

        self.assertEqual(hy2.outbound["type"], "hysteria2")
        self.assertTrue(hy2.outbound["tls"]["insecure"])
        self.assertEqual(shadowsocks.outbound["method"], "aes-128-gcm")
        self.assertEqual(shadowsocks.outbound["password"], "ÿÿ")

    def test_parses_shadowsocks_sip002_variants(self):
        plaintext = parse_proxy_uri(
            "ss://2022-blake3-aes-128-gcm%3Asecret@s.example:443#AEAD2022"
        )
        legacy = parse_proxy_uri(
            "ss://YWVzLTEyOC1nY206cGFzc0BzLmV4YW1wbGU6ODM4OA==#Legacy"
        )

        self.assertIsNotNone(plaintext)
        self.assertIsNotNone(legacy)
        self.assertEqual(
            plaintext.outbound,
            {
                "type": "shadowsocks",
                "server": "s.example",
                "server_port": 443,
                "method": "2022-blake3-aes-128-gcm",
                "password": "secret",
            },
        )
        self.assertEqual(
            legacy.outbound,
            {
                "type": "shadowsocks",
                "server": "s.example",
                "server_port": 8388,
                "method": "aes-128-gcm",
                "password": "pass",
            },
        )

    def test_hysteria2_preserves_userpass_as_authentication_password(self):
        parsed = parse_proxy_uri(
            "hysteria2://user:pass%3Apart@h.example:443#UserPass"
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.outbound["password"], "user:pass:part")

    def test_hysteria2_defaults_port_and_maps_port_hopping_ranges(self):
        default_port = parse_proxy_uri("hysteria2://password@h.example#Default")
        hopping = parse_proxy_uri(
            "hysteria2://password@h.example:20000-20002,30000#Hopping"
        )

        self.assertIsNotNone(default_port)
        self.assertEqual(default_port.outbound["server_port"], 443)
        self.assertNotIn("server_ports", default_port.outbound)
        self.assertIsNotNone(hopping)
        self.assertNotIn("server_port", hopping.outbound)
        self.assertEqual(
            hopping.outbound["server_ports"], ["20000:20002", "30000"]
        )

    def test_rejects_invalid_uuids_and_protocol_enums(self):
        vmess_bad_uuid = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "443",
                    "id": "not-a-uuid",
                    "scy": "auto",
                }
            ).encode("utf-8")
        ).decode("ascii")
        vmess_bad_security = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": "invalid",
                }
            ).encode("utf-8")
        ).decode("ascii")
        vmess_bad_transport = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": "auto",
                    "net": "invalid",
                }
            ).encode("utf-8")
        ).decode("ascii")
        vmess_bad_tls = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": "auto",
                    "tls": "invalid",
                }
            ).encode("utf-8")
        ).decode("ascii")
        invalid = {
            "vmess UUID": f"vmess://{vmess_bad_uuid}",
            "vmess security": f"vmess://{vmess_bad_security}",
            "vmess transport": f"vmess://{vmess_bad_transport}",
            "vmess TLS": f"vmess://{vmess_bad_tls}",
            "vless UUID": "vless://not-a-uuid@v.example:443#Invalid",
            "vless security": (
                "vless://00000000-0000-0000-0000-000000000001@v.example:443"
                "?security=invalid#Invalid"
            ),
            "vless flow": (
                "vless://00000000-0000-0000-0000-000000000001@v.example:443"
                "?flow=invalid#Invalid"
            ),
            "vless transport": (
                "vless://00000000-0000-0000-0000-000000000001@v.example:443"
                "?type=invalid#Invalid"
            ),
            "tuic UUID": "tuic://not-a-uuid:password@u.example:443#Invalid",
            "tuic congestion": (
                "tuic://00000000-0000-0000-0000-000000000001:password@u.example:443"
                "?congestion_control=invalid#Invalid"
            ),
            "hysteria2 obfs": (
                "hysteria2://password@h.example:443?obfs=invalid#Invalid"
            ),
            "shadowsocks method": (
                "ss://unsupported%3Apassword@s.example:8388#Invalid"
            ),
            "trojan security": (
                "trojan://password@t.example:443?security=invalid#Invalid"
            ),
            "trojan transport": (
                "trojan://password@t.example:443?type=invalid#Invalid"
            ),
        }

        for label, uri in invalid.items():
            with self.subTest(label):
                self.assertTrue(parse_proxy_uri(uri) is None)

    def test_maps_vmess_h2_network_to_http_transport(self):
        payload = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": "auto",
                    "net": "h2",
                    "host": "cdn.example",
                    "path": "/h2",
                }
            ).encode("utf-8")
        ).decode("ascii")

        parsed = parse_proxy_uri(f"vmess://{payload}")

        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed.outbound.get("transport"),
            {"type": "http", "host": ["cdn.example"], "path": "/h2"},
        )

    def test_maps_canonical_tcp_http_disguise_to_exact_outbounds(self):
        vmess_payload = base64.b64encode(
            json.dumps(
                {
                    "ps": "VMess HTTP",
                    "add": "m.example",
                    "port": "80",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "aid": "0",
                    "scy": "auto",
                    "net": "tcp",
                    "type": "http",
                    "host": "one.example,two.example",
                    "path": "/vmess-http",
                }
            ).encode("utf-8")
        ).decode("ascii")
        cases = {
            f"vmess://{vmess_payload}": {
                "type": "vmess",
                "server": "m.example",
                "server_port": 80,
                "uuid": "00000000-0000-0000-0000-000000000001",
                "security": "auto",
                "alter_id": 0,
                "transport": {
                    "type": "http",
                    "host": ["one.example", "two.example"],
                    "path": "/vmess-http",
                },
            },
            (
                "vless://00000000-0000-0000-0000-000000000001@v.example:80"
                "?type=tcp&headerType=http&host=one.example%2Ctwo.example"
                "&path=%2Fvless-http#VLESS"
            ): {
                "type": "vless",
                "server": "v.example",
                "server_port": 80,
                "uuid": "00000000-0000-0000-0000-000000000001",
                "transport": {
                    "type": "http",
                    "host": ["one.example", "two.example"],
                    "path": "/vless-http",
                },
            },
            (
                "trojan://password@t.example:443?security=tls&sni=t.example"
                "&type=tcp&headerType=http&host=cdn.example"
                "&path=%2Ftrojan-http#Trojan"
            ): {
                "type": "trojan",
                "server": "t.example",
                "server_port": 443,
                "password": "password",
                "transport": {
                    "type": "http",
                    "host": ["cdn.example"],
                    "path": "/trojan-http",
                },
                "tls": {"enabled": True, "server_name": "t.example"},
            },
        }

        for uri, expected_outbound in cases.items():
            with self.subTest(expected_outbound["type"]):
                parsed = parse_proxy_uri(uri)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.outbound, expected_outbound)

    def test_rejects_unrepresentable_tcp_header_variants(self):
        vmess_payload = base64.b64encode(
            json.dumps(
                {
                    "add": "m.example",
                    "port": "80",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": "auto",
                    "net": "tcp",
                    "type": "unsupported-header",
                }
            ).encode("utf-8")
        ).decode("ascii")
        uris = [
            f"vmess://{vmess_payload}",
            (
                "vless://00000000-0000-0000-0000-000000000001@v.example:80"
                "?type=tcp&headerType=unsupported-header#VLESS"
            ),
            (
                "trojan://password@t.example:443"
                "?type=tcp&headerType=unsupported-header#Trojan"
            ),
        ]

        for uri in uris:
            with self.subTest(uri.split(":", 1)[0]):
                self.assertIsNone(parse_proxy_uri(uri))

    def test_rejects_shadowsocks_plugin_instead_of_discarding_it(self):
        uri = (
            "ss://YWVzLTEyOC1nY206cGFzcw==@s.example:8388"
            "?plugin=v2ray-plugin%3Btls%3Bhost%3Dcdn.example#SS"
        )

        self.assertIsNone(parse_proxy_uri(uri))

    def test_omits_null_vmess_optional_fields(self):
        payload = base64.b64encode(
            json.dumps(
                {
                    "ps": None,
                    "add": "m.example",
                    "port": "443",
                    "id": "00000000-0000-0000-0000-000000000001",
                    "scy": None,
                    "aid": None,
                    "net": "ws",
                    "path": None,
                    "host": None,
                    "tls": "tls",
                    "sni": None,
                    "fp": None,
                    "allowInsecure": None,
                }
            ).encode("utf-8")
        ).decode("ascii")

        parsed = parse_proxy_uri(f"vmess://{payload}")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.display_name, "VMess")
        self.assertNotIn("alter_id", parsed.outbound)
        self.assertEqual(parsed.outbound["transport"], {"type": "ws"})
        self.assertEqual(parsed.outbound["tls"], {"enabled": True})

    def test_omits_empty_optional_transport_and_tls_fields(self):
        parsed = parse_proxy_uri(
            "vless://00000000-0000-0000-0000-000000000001@v.example:80#Plain"
        )

        self.assertNotIn("transport", parsed.outbound)
        self.assertNotIn("tls", parsed.outbound)

    def test_rejects_malformed_or_unsupported_uris(self):
        invalid = [
            "vmess://not-base64",
            "vless://id@host.example:not-a-port",
            "trojan://@host.example:443",
            "socks://user:pass@host.example:1080",
        ]

        for uri in invalid:
            with self.subTest(uri.split(":", 1)[0]):
                self.assertIsNone(parse_proxy_uri(uri))


class SingboxConfigBuilderTests(unittest.TestCase):
    def test_builds_selector_urltest_nodes_and_route_references(self):
        template = minimal_template()
        uris = [
            "vless://00000000-0000-0000-0000-000000000001@a.example:443"
            "?security=tls#Node",
            "trojan://password@b.example:443?security=tls#Node",
        ]

        config = build_singbox_config(uris, template)

        by_tag = {outbound["tag"]: outbound for outbound in config["outbounds"]}
        self.assertEqual(config["route"]["final"], "proxy")
        self.assertEqual(by_tag["proxy"]["default"], "auto")
        self.assertEqual(by_tag["auto"]["outbounds"], ["Node", "Node-2"])
        self.assertEqual(
            by_tag["proxy"]["outbounds"],
            ["auto", "Node", "Node-2", "direct"],
        )

    def test_same_endpoint_with_different_credentials_is_not_deduplicated(self):
        uris = [
            "vless://00000000-0000-0000-0000-000000000001@a.example:443"
            "?security=tls#A",
            "vless://00000000-0000-0000-0000-000000000002@a.example:443"
            "?security=tls#B",
        ]

        config = build_singbox_config(uris, minimal_template())

        self.assertEqual(len(config["outbounds"]), 5)

    def test_deduplicates_normalized_outbounds_before_assigning_tags(self):
        uris = [
            "vless://00000000-0000-0000-0000-000000000001@a.example:443"
            "?security=tls#First",
            "vless://00000000-0000-0000-0000-000000000001@a.example:443"
            "?security=tls#Second",
        ]

        config = build_singbox_config(uris, minimal_template())

        self.assertEqual(len(config["outbounds"]), 4)
        self.assertEqual(config["outbounds"][1]["outbounds"], ["First"])

    def test_rejects_duplicate_outbound_tags(self):
        template = minimal_template()
        template["outbounds"].append({"type": "direct", "tag": "direct"})

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_selector_or_urltest_outbound_references(self):
        template = minimal_template()
        template["outbounds"] = []

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_route_final_reference(self):
        template = minimal_template()
        template["route"]["final"] = "missing"

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_route_action_outbound_reference(self):
        template = minimal_template()
        template["route"]["rules"] = [
            {"action": "route", "outbound": "missing"}
        ]

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_dns_final_reference(self):
        template = minimal_template()
        template["dns"]["final"] = "missing"

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_dns_detour_outbound_reference(self):
        template = minimal_template()
        template["dns"]["servers"][0]["detour"] = "missing"

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_default_domain_resolver_reference(self):
        template = minimal_template()
        template["route"]["default_domain_resolver"] = "missing"

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_missing_object_default_domain_resolver_reference(self):
        template = minimal_template()
        template["route"]["default_domain_resolver"] = {"server": "missing"}

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_object_default_domain_resolver_without_server(self):
        template = minimal_template()
        template["route"]["default_domain_resolver"] = {}

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_object_default_domain_resolver_with_empty_server(self):
        template = minimal_template()
        template["route"]["default_domain_resolver"] = {"server": ""}

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_rejects_object_default_domain_resolver_with_non_string_server(self):
        template = minimal_template()
        template["route"]["default_domain_resolver"] = {"server": 0}

        with self.assertRaises(ValueError):
            build_singbox_config([VALID_VLESS], template)

    def test_does_not_mutate_template(self):
        template = minimal_template()
        original = copy.deepcopy(template)

        build_singbox_config([VALID_VLESS], template)

        self.assertEqual(template, original)

    def test_zero_valid_nodes_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            template_path = Path(directory) / "template.json"
            output_path = Path(directory) / "config.json"
            template_path.write_text(
                json.dumps(minimal_template()),
                encoding="utf-8",
            )
            output_path.write_text("old-config", encoding="utf-8")

            with self.assertRaises(NoValidOutboundsError):
                write_singbox_config(["not-a-proxy"], template_path, output_path)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "old-config")

    def test_write_replaces_existing_config_with_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template_path = root / "template.json"
            output_path = root / "config.json"
            template_path.write_text(json.dumps(minimal_template()), encoding="utf-8")
            output_path.write_text("old-config", encoding="utf-8")

            write_singbox_config([VALID_VLESS], template_path, output_path)

            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["route"]["final"], "proxy")
            self.assertEqual(set(root.iterdir()), {template_path, output_path})

    def test_write_failure_keeps_previous_config_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template_path = root / "template.json"
            output_path = root / "config.json"
            template_path.write_text(json.dumps(minimal_template()), encoding="utf-8")
            output_path.write_text("old-config", encoding="utf-8")

            with patch("file_utils.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_singbox_config([VALID_VLESS], template_path, output_path)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "old-config")
            self.assertEqual(set(root.iterdir()), {template_path, output_path})

    def test_official_android_template_builds_a_valid_config_graph(self):
        template_path = Path(__file__).parents[1] / "sing-box_template.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))

        config = build_singbox_config([VALID_VLESS], template)

        tun = config["inbounds"][0]
        self.assertEqual(tun["dns_mode"], "hijack")
        self.assertEqual(
            tun["address"],
            ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
        )
        self.assertTrue(tun["auto_route"])
        self.assertEqual(tun["exclude_package"], ["io.nekohasekai.sfa"])
        self.assertEqual(tun["stack"], "gvisor")
        self.assertEqual(config["dns"]["final"], "remote")
        self.assertEqual(config["dns"]["servers"][1]["detour"], "proxy")
        self.assertIn(
            {
                "network": "udp",
                "port": 443,
                "action": "reject",
                "method": "default",
            },
            config["route"]["rules"],
        )
        self.assertEqual(config["route"]["final"], "proxy")


if __name__ == "__main__":
    unittest.main()
