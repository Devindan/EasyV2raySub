import html
import re
import sys
from collections.abc import Callable
from urllib.parse import urlparse

SUPPORTED_SCHEMES = ("vmess", "vless", "trojan", "ss", "hy2", "hysteria2", "tuic", "anytls")


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


def crawl_links(
    urls: list[str],
    additional_regex: str | None = None,
    fetcher: Callable[[str], str] | None = None,
) -> list[str]:
    additional_pattern = re.compile(additional_regex) if additional_regex else None

    if fetcher is None:
        import requests
        from bs4 import BeautifulSoup

        def fetcher(url: str) -> str:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser").get_text("\n")

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
