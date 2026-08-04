"""Convert supported proxy URIs to sing-box outbound dictionaries."""

from __future__ import annotations

import base64
import binascii
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import ParseResult, parse_qs, unquote, urlparse
from uuid import UUID

from file_utils import atomic_write_text


VMESS_SECURITY_METHODS = {
    "auto",
    "none",
    "zero",
    "aes-128-gcm",
    "chacha20-poly1305",
    "aes-128-ctr",
}
SHADOWSOCKS_METHODS = {
    "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
    "none",
    "aes-128-gcm",
    "aes-192-gcm",
    "aes-256-gcm",
    "chacha20-ietf-poly1305",
    "xchacha20-ietf-poly1305",
    "aes-128-ctr",
    "aes-192-ctr",
    "aes-256-ctr",
    "aes-128-cfb",
    "aes-192-cfb",
    "aes-256-cfb",
    "rc4-md5",
    "chacha20-ietf",
    "xchacha20",
}
TUIC_CONGESTION_CONTROLS = {"cubic", "new_reno", "bbr"}
HYSTERIA2_OBFS_TYPES = {"salamander", "gecko"}
TRANSPORT_TYPES = {"", "none", "tcp", "ws", "grpc", "http", "h2", "httpupgrade"}
VLESS_SECURITY_MODES = {"", "none", "tls", "reality"}
VLESS_FLOWS = {"", "xtls-rprx-vision"}


@dataclass(frozen=True)
class ParsedOutbound:
    outbound: dict[str, object]
    display_name: str


class NoValidOutboundsError(ValueError):
    """Raised when no supported proxy URI can produce an outbound."""


Query = dict[str, list[str]]
Parser = Callable[[ParseResult], ParsedOutbound]


def build_singbox_config(
    uris: Sequence[str],
    template: Mapping[str, object],
) -> dict[str, object]:
    """Build a sing-box configuration without mutating the template."""
    config = copy.deepcopy(dict(template))
    static_outbounds = config.get("outbounds", [])
    if not isinstance(static_outbounds, list):
        raise ValueError("template outbounds must be a list")

    used_tags = {"proxy", "auto"}
    used_tags.update(
        outbound["tag"]
        for outbound in static_outbounds
        if isinstance(outbound, dict) and isinstance(outbound.get("tag"), str)
    )
    seen_outbounds: set[str] = set()
    nodes: list[dict[str, object]] = []
    node_tags: list[str] = []

    for uri in uris:
        parsed = parse_proxy_uri(uri)
        if parsed is None:
            continue

        normalized = json.dumps(
            parsed.outbound,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if normalized in seen_outbounds:
            continue
        seen_outbounds.add(normalized)

        tag = _unique_tag(parsed.display_name, used_tags)
        node = dict(parsed.outbound)
        node["tag"] = tag
        nodes.append(node)
        node_tags.append(tag)

    if not nodes:
        raise NoValidOutboundsError("no valid proxy outbounds")

    selector = {
        "type": "selector",
        "tag": "proxy",
        "outbounds": ["auto", *node_tags, "direct"],
        "default": "auto",
        "interrupt_exist_connections": False,
    }
    urltest = {
        "type": "urltest",
        "tag": "auto",
        "outbounds": node_tags,
        "url": "https://www.gstatic.com/generate_204",
        "interval": "3m",
        "tolerance": 50,
        "idle_timeout": "30m",
        "interrupt_exist_connections": False,
    }
    config["outbounds"] = [selector, urltest, *nodes, *static_outbounds]
    _validate_config_references(config)
    return config


def write_singbox_config(
    uris: Sequence[str],
    template_path: str | Path,
    output_path: str | Path,
) -> None:
    """Build and write a sing-box configuration from a JSON template."""
    template = json.loads(Path(template_path).read_text(encoding="utf-8"))
    if not isinstance(template, dict):
        raise ValueError("template must be a JSON object")
    config = build_singbox_config(uris, template)
    content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(output_path, content)


def _unique_tag(display_name: str, used_tags: set[str]) -> str:
    base = display_name or "Proxy"
    tag = base
    suffix = 2
    while tag in used_tags:
        tag = f"{base}-{suffix}"
        suffix += 1
    used_tags.add(tag)
    return tag


def _validate_config_references(config: Mapping[str, object]) -> None:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        raise ValueError("config outbounds must be a list")

    outbound_tags: set[str] = set()
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            raise ValueError("each outbound must be an object")
        tag = outbound.get("tag")
        if not isinstance(tag, str) or not tag:
            raise ValueError("each outbound must have a non-empty tag")
        if tag in outbound_tags:
            raise ValueError(f"duplicate outbound tag: {tag}")
        outbound_tags.add(tag)

    for outbound in outbounds:
        if outbound.get("type") not in {"selector", "urltest"}:
            continue
        references = outbound.get("outbounds")
        if not isinstance(references, list):
            raise ValueError("selector and urltest outbounds must be a list")
        for reference in references:
            _require_reference(reference, outbound_tags, "outbound")
        if outbound.get("type") == "selector" and outbound.get("default"):
            _require_reference(outbound["default"], outbound_tags, "outbound")

    route = config.get("route")
    if route is not None and not isinstance(route, dict):
        raise ValueError("route must be an object")
    if isinstance(route, dict):
        route_final = route.get("final")
        if route_final:
            _require_reference(route_final, outbound_tags, "route final outbound")
        _validate_route_rule_references(route.get("rules", []), outbound_tags)

    dns = config.get("dns")
    if dns is not None and not isinstance(dns, dict):
        raise ValueError("dns must be an object")
    dns_tags: set[str] = set()
    if isinstance(dns, dict):
        servers = dns.get("servers", [])
        if not isinstance(servers, list):
            raise ValueError("dns servers must be a list")
        for server in servers:
            if not isinstance(server, dict):
                raise ValueError("each DNS server must be an object")
            tag = server.get("tag")
            if isinstance(tag, str) and tag:
                dns_tags.add(tag)
            detour = server.get("detour")
            if detour:
                _require_reference(detour, outbound_tags, "DNS detour outbound")
        dns_final = dns.get("final")
        if dns_final:
            _require_reference(dns_final, dns_tags, "DNS final server")

    if isinstance(route, dict):
        resolver = route.get("default_domain_resolver")
        if isinstance(resolver, str) and resolver:
            _require_reference(resolver, dns_tags, "default domain resolver")
        elif isinstance(resolver, dict):
            server = resolver.get("server")
            if not isinstance(server, str) or not server:
                raise ValueError(
                    "default domain resolver object requires a non-empty server"
                )
            _require_reference(
                server,
                dns_tags,
                "default domain resolver",
            )
        elif resolver is not None and not isinstance(resolver, (str, dict)):
            raise ValueError("default domain resolver must be a DNS tag or object")


def _validate_route_rule_references(
    rules: object,
    outbound_tags: set[str],
) -> None:
    if not isinstance(rules, list):
        raise ValueError("route rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each route rule must be an object")
        outbound = rule.get("outbound")
        if outbound:
            _require_reference(outbound, outbound_tags, "route action outbound")
        nested_rules = rule.get("rules")
        if nested_rules is not None:
            _validate_route_rule_references(nested_rules, outbound_tags)


def _require_reference(
    reference: object,
    available_tags: set[str],
    description: str,
) -> None:
    if not isinstance(reference, str) or reference not in available_tags:
        raise ValueError(f"unknown {description} reference")


def parse_proxy_uri(uri: str) -> ParsedOutbound | None:
    """Parse one supported proxy URI, returning ``None`` when it is invalid."""
    if not isinstance(uri, str) or not uri:
        return None

    parsers: dict[str, Parser] = {
        "vmess": _parse_vmess,
        "vless": _parse_vless,
        "trojan": _parse_trojan,
        "ss": _parse_shadowsocks,
        "hy2": _parse_hysteria2,
        "hysteria2": _parse_hysteria2,
        "tuic": _parse_tuic,
        "anytls": _parse_anytls,
    }

    try:
        parsed = urlparse(uri)
        parser = parsers.get(parsed.scheme.lower())
        if parser is None:
            return None
        return parser(parsed)
    except (binascii.Error, json.JSONDecodeError, TypeError, UnicodeError, ValueError):
        return None


def _decode_base64(value: str) -> str:
    compact = "".join(value.split())
    padded = compact + "=" * (-len(compact) % 4)
    decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    return decoded.decode("utf-8")


def _query(parsed: ParseResult) -> Query:
    return parse_qs(parsed.query, keep_blank_values=True)


def _first(query: Query, *names: str) -> str:
    for name in names:
        values = query.get(name)
        if values:
            return values[0]
    return ""


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _endpoint(parsed: ParseResult) -> tuple[str, int]:
    server = parsed.hostname
    port = parsed.port
    if not server or port is None or not 1 <= port <= 65535:
        raise ValueError("missing or invalid proxy endpoint")
    return server, port


def _hysteria2_endpoint(parsed: ParseResult) -> tuple[str, int | None, list[str]]:
    server = parsed.hostname
    if not server:
        raise ValueError("missing Hysteria2 server")

    authority = parsed.netloc.rsplit("@", 1)[-1]
    if authority.startswith("["):
        closing_bracket = authority.find("]")
        if closing_bracket < 0:
            raise ValueError("invalid IPv6 server")
        remainder = authority[closing_bracket + 1 :]
        port_spec = remainder[1:] if remainder.startswith(":") else ""
    else:
        port_spec = authority.rsplit(":", 1)[1] if ":" in authority else ""

    if not port_spec:
        return server, 443, []
    if port_spec.isdigit():
        port = int(port_spec)
        if not 1 <= port <= 65535:
            raise ValueError("invalid Hysteria2 port")
        return server, port, []

    server_ports: list[str] = []
    for item in port_spec.split(","):
        if not item:
            raise ValueError("empty Hysteria2 port range")
        if "-" in item:
            start_text, separator, end_text = item.partition("-")
            if not separator or not start_text.isdigit() or not end_text.isdigit():
                raise ValueError("invalid Hysteria2 port range")
            start = int(start_text)
            end = int(end_text)
            if not 1 <= start <= end <= 65535:
                raise ValueError("invalid Hysteria2 port range")
            server_ports.append(f"{start}:{end}")
        elif item.isdigit() and 1 <= int(item) <= 65535:
            server_ports.append(str(int(item)))
        else:
            raise ValueError("invalid Hysteria2 port")
    return server, None, server_ports


def _display_name(parsed: ParseResult, fallback: str) -> str:
    name = unquote(parsed.fragment).strip()
    return name or fallback


def _validate_uuid(value: str) -> None:
    if str(UUID(value)) != value.lower():
        raise ValueError("invalid UUID")


def _validate_transport_type(values: dict[str, object], type_key: str) -> None:
    transport_type = _optional_string(values.get(type_key)).lower()
    if transport_type not in TRANSPORT_TYPES:
        raise ValueError("invalid transport type")


def _tls(
    query: Query,
    *,
    required: bool,
    reality: bool = False,
) -> dict[str, object] | None:
    if not required:
        return None

    result: dict[str, object] = {"enabled": True}
    server_name = _first(query, "sni", "serverName", "servername")
    if server_name:
        result["server_name"] = server_name

    if _is_true(_first(query, "insecure", "allowInsecure")):
        result["insecure"] = True

    fingerprint = _first(query, "fp")
    if fingerprint:
        result["utls"] = {"enabled": True, "fingerprint": fingerprint}

    if reality:
        public_key = _first(query, "pbk", "publicKey")
        short_id = _first(query, "sid", "shortId")
        if not public_key:
            raise ValueError("missing Reality public key")
        result["reality"] = {
            "enabled": True,
            "public_key": public_key,
            "short_id": short_id,
        }

    return result


def _vmess_tls(payload: dict[str, object]) -> dict[str, object] | None:
    security = _optional_string(payload.get("tls")).lower()
    if not security or security == "none":
        return None

    result: dict[str, object] = {"enabled": True}
    server_name = _optional_string(payload.get("sni"))
    if server_name:
        result["server_name"] = server_name

    if _is_true(_optional_string(payload.get("allowInsecure"))):
        result["insecure"] = True

    fingerprint = _optional_string(payload.get("fp"))
    if fingerprint:
        result["utls"] = {"enabled": True, "fingerprint": fingerprint}
    return result


def _transport(
    values: dict[str, object],
    type_key: str,
    *,
    header_type_key: str,
) -> dict[str, object] | None:
    transport_type = _optional_string(values.get(type_key)).lower()
    if transport_type == "h2":
        transport_type = "http"
    elif transport_type == "tcp":
        header_type = _optional_string(values.get(header_type_key)).lower()
        if header_type in {"", "none"}:
            return None
        if header_type != "http":
            raise ValueError("unsupported TCP header type")
        transport_type = "http"
    if transport_type not in {"ws", "grpc", "http", "httpupgrade"}:
        return None

    result: dict[str, object] = {"type": transport_type}
    path = _optional_string(values.get("path"))
    host = _optional_string(values.get("host"))

    if transport_type == "grpc":
        service_name = _optional_string(
            values.get("serviceName", values.get("service_name", path))
        )
        if service_name:
            result["service_name"] = service_name
        return result

    if path:
        result["path"] = path

    if transport_type == "ws":
        if host:
            result["headers"] = {"Host": host}
    elif transport_type == "http":
        if host:
            result["host"] = [item.strip() for item in host.split(",") if item.strip()]
        method = _optional_string(values.get("method"))
        if method:
            result["method"] = method
    elif host:
        result["host"] = host

    return result


def _query_values(query: Query) -> dict[str, object]:
    return {key: values[0] for key, values in query.items() if values}


def _parse_vmess(parsed: ParseResult) -> ParsedOutbound:
    payload = json.loads(_decode_base64(parsed.netloc + parsed.path))
    if not isinstance(payload, dict):
        raise ValueError("VMess payload is not an object")

    server = payload.get("add")
    user_id = payload.get("id")
    if not isinstance(server, str) or not server or not isinstance(user_id, str) or not user_id:
        raise ValueError("missing VMess credentials")
    _validate_uuid(user_id)

    port = int(payload.get("port", 0))
    if not 1 <= port <= 65535:
        raise ValueError("invalid VMess port")

    security = str(payload.get("scy") or "auto")
    if security not in VMESS_SECURITY_METHODS:
        raise ValueError("invalid VMess security")

    outbound: dict[str, object] = {
        "type": "vmess",
        "server": server,
        "server_port": port,
        "uuid": user_id,
        "security": security,
    }
    alter_id = payload.get("aid")
    if alter_id not in (None, ""):
        outbound["alter_id"] = int(alter_id)

    _validate_transport_type(payload, "net")
    transport = _transport(payload, "net", header_type_key="type")
    if transport:
        outbound["transport"] = transport

    tls_mode = _optional_string(payload.get("tls")).lower()
    if tls_mode not in {"", "none", "tls"}:
        raise ValueError("invalid VMess TLS mode")
    tls = _vmess_tls(payload)
    if tls:
        outbound["tls"] = tls

    display_name = _optional_string(payload.get("ps")).strip() or "VMess"
    return ParsedOutbound(outbound, display_name)


def _parse_vless(parsed: ParseResult) -> ParsedOutbound:
    server, port = _endpoint(parsed)
    user_id = unquote(parsed.username or "")
    if not user_id:
        raise ValueError("missing VLESS UUID")
    _validate_uuid(user_id)

    query = _query(parsed)
    outbound: dict[str, object] = {
        "type": "vless",
        "server": server,
        "server_port": port,
        "uuid": user_id,
    }
    flow = _first(query, "flow")
    if flow not in VLESS_FLOWS:
        raise ValueError("invalid VLESS flow")
    if flow:
        outbound["flow"] = flow

    query_values = _query_values(query)
    _validate_transport_type(query_values, "type")
    transport = _transport(query_values, "type", header_type_key="headerType")
    if transport:
        outbound["transport"] = transport

    security = _first(query, "security").lower()
    if security not in VLESS_SECURITY_MODES:
        raise ValueError("invalid VLESS security mode")
    tls = _tls(query, required=security in {"tls", "reality"}, reality=security == "reality")
    if tls:
        outbound["tls"] = tls

    return ParsedOutbound(outbound, _display_name(parsed, "VLESS"))


def _parse_trojan(parsed: ParseResult) -> ParsedOutbound:
    server, port = _endpoint(parsed)
    password = unquote(parsed.username or "")
    if not password:
        raise ValueError("missing Trojan password")

    query = _query(parsed)
    security = _first(query, "security").lower()
    if security not in {"", "tls"}:
        raise ValueError("invalid Trojan security mode")
    outbound: dict[str, object] = {
        "type": "trojan",
        "server": server,
        "server_port": port,
        "password": password,
    }

    query_values = _query_values(query)
    _validate_transport_type(query_values, "type")
    transport = _transport(query_values, "type", header_type_key="headerType")
    if transport:
        outbound["transport"] = transport

    tls = _tls(query, required=True)
    if tls:
        outbound["tls"] = tls

    return ParsedOutbound(outbound, _display_name(parsed, "Trojan"))


def _parse_shadowsocks(parsed: ParseResult) -> ParsedOutbound:
    if "plugin" in _query(parsed):
        raise ValueError("Shadowsocks plugins are unsupported")

    if "@" in parsed.netloc:
        server, port = _endpoint(parsed)
        credentials = unquote(parsed.netloc.rsplit("@", 1)[0])
        if ":" not in credentials:
            credentials = _decode_base64(credentials)
    else:
        legacy = _decode_base64(parsed.netloc + parsed.path)
        credentials, separator, endpoint = legacy.rpartition("@")
        if not separator:
            raise ValueError("invalid legacy Shadowsocks URI")
        server, port = _endpoint(urlparse(f"//{endpoint}"))

    method, separator, password = credentials.partition(":")
    if not separator or not method or not password:
        raise ValueError("invalid Shadowsocks credentials")
    if method not in SHADOWSOCKS_METHODS:
        raise ValueError("invalid Shadowsocks method")

    outbound: dict[str, object] = {
        "type": "shadowsocks",
        "server": server,
        "server_port": port,
        "method": method,
        "password": password,
    }
    return ParsedOutbound(outbound, _display_name(parsed, "Shadowsocks"))


def _parse_hysteria2(parsed: ParseResult) -> ParsedOutbound:
    server, port, server_ports = _hysteria2_endpoint(parsed)
    password = unquote(parsed.netloc.rsplit("@", 1)[0]) if "@" in parsed.netloc else ""
    if not password:
        raise ValueError("missing Hysteria2 password")

    query = _query(parsed)
    outbound: dict[str, object] = {
        "type": "hysteria2",
        "server": server,
        "password": password,
    }
    if server_ports:
        outbound["server_ports"] = server_ports
    elif port is not None:
        outbound["server_port"] = port
    obfs_type = _first(query, "obfs")
    if obfs_type:
        if obfs_type not in HYSTERIA2_OBFS_TYPES:
            raise ValueError("invalid Hysteria2 obfuscation type")
        obfs: dict[str, object] = {"type": obfs_type}
        obfs_password = _first(query, "obfs-password", "obfs_password")
        if obfs_password:
            obfs["password"] = obfs_password
        outbound["obfs"] = obfs

    tls = _tls(query, required=True)
    if tls:
        outbound["tls"] = tls

    return ParsedOutbound(outbound, _display_name(parsed, "Hysteria2"))


def _parse_tuic(parsed: ParseResult) -> ParsedOutbound:
    server, port = _endpoint(parsed)
    user_id = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not user_id or not password:
        raise ValueError("missing TUIC credentials")
    _validate_uuid(user_id)

    query = _query(parsed)
    outbound: dict[str, object] = {
        "type": "tuic",
        "server": server,
        "server_port": port,
        "uuid": user_id,
        "password": password,
    }
    congestion_control = _first(query, "congestion_control", "congestion-control")
    if congestion_control:
        if congestion_control not in TUIC_CONGESTION_CONTROLS:
            raise ValueError("invalid TUIC congestion control")
        outbound["congestion_control"] = congestion_control

    tls = _tls(query, required=True)
    if tls:
        outbound["tls"] = tls

    return ParsedOutbound(outbound, _display_name(parsed, "TUIC"))


def _parse_anytls(parsed: ParseResult) -> ParsedOutbound:
    server, port = _endpoint(parsed)
    password = unquote(parsed.username or "")
    if not password:
        raise ValueError("missing AnyTLS password")

    query = _query(parsed)
    outbound: dict[str, object] = {
        "type": "anytls",
        "server": server,
        "server_port": port,
        "password": password,
    }
    tls = _tls(query, required=True)
    if tls:
        outbound["tls"] = tls

    return ParsedOutbound(outbound, _display_name(parsed, "AnyTLS"))
