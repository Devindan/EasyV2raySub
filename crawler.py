import html
import re
import sys
from collections.abc import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

SUPPORTED_SCHEMES = ("vmess", "vless", "trojan", "ss", "hy2", "hysteria2", "tuic", "anytls")

# Cloudflare 邮箱保护标签。在 HTML 字符串层面还原，而不是在 DOM 树上 replace_with：
# replace_with 会让解码文本成为独立文本节点，get_text("\n") 遂在链接内部插入换行
# （例如 anytls:// 被拆成多行），正则无法再匹配出完整链接。
CF_EMAIL_TAG_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][\w-]*)\b[^>]*\bdata-cfemail=[\"'](?P<code>[0-9a-fA-F]+)[\"'][^>]*>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)


class NoLinksError(RuntimeError):
    pass


def _extract_links(
        text: str,
        additional_pattern: re.Pattern[str] | None,
) -> list[str]:
    decoded = html.unescape(text)
    pattern = rf"(?:{'|'.join(SUPPORTED_SCHEMES)})://[^\s<>'\"]+"
    matches = re.findall(pattern, decoded)
    if additional_pattern:
        matches.extend(match.group(0) for match in additional_pattern.finditer(decoded))
    return list(dict.fromkeys(matches))


def extract_links(text: str, additional_regex: str | None = None) -> list[str]:
    additional_pattern = re.compile(additional_regex) if additional_regex else None
    return _extract_links(text, additional_pattern)


def _sanitized_hostname(url: str) -> str:
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        hostname = None
    if not hostname:
        return "unknown"
    sanitized = re.sub(r"[^A-Za-z0-9.:-]", "?", hostname)
    return sanitized[:255] or "unknown"


def _decode_cf_email(encoded: str) -> str:
    data = bytes.fromhex(encoded)
    if not data:
        raise ValueError("empty Cloudflare email payload")
    return bytes(b ^ data[0] for b in data[1:]).decode("utf-8")


def _restore_cf_emails(text: str) -> str:
    """Replace Cloudflare-obfuscated email tags with their decoded text.

    The substitution happens on the raw HTML string rather than on the parsed
    tree, so the decoded text stays part of its surrounding text node.  Parsing
    afterwards with get_text("\\n") then only splits on real tag boundaries and
    never breaks a proxy URI in half.
    """
    def replace(match: re.Match[str]) -> str:
        try:
            decoded = _decode_cf_email(match.group("code"))
        except (ValueError, UnicodeDecodeError):
            return match.group(0)
        return html.escape(decoded, quote=False)

    return CF_EMAIL_TAG_RE.sub(replace, text)


def _fetcher(url: str) -> str:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(_restore_cf_emails(response.text), "html.parser")
    return soup.get_text("\n")


def crawl_links(
        urls: list[str],
        additional_regex: str | None = None,
        fetcher: Callable[[str], str] | None = None,
) -> list[str]:
    additional_pattern = re.compile(additional_regex) if additional_regex else None

    if fetcher is None:
        fetcher = _fetcher

    links = []
    for source_index, url in enumerate(urls, start=1):
        try:
            links.extend(_extract_links(fetcher(url), additional_pattern))
        except Exception as error:
            print(
                f"Source {source_index} ({_sanitized_hostname(url)}) failed: "
                f"{type(error).__name__}",
                file=sys.stderr,
            )
            continue

    links = list(dict.fromkeys(links))
    if not links:
        raise NoLinksError("No proxy links found")
    return links
