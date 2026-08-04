import base64
import json
import re
from pathlib import Path
from typing import Sequence

from file_utils import atomic_write_text


DOMAIN_REGEX = r"([a-zA-Z\d][a-zA-Z\d\-]{1,62}\.){1,3}[a-zA-Z]{2,63}"


def _replace_node_name(link: str) -> str:
    try:
        link_parts = link.split("#")
        if len(link_parts) == 2:
            new_name = re.sub(DOMAIN_REGEX, "EasyV2raySub", link_parts[1])
            return link_parts[0] + "#" + new_name

        scheme, encoded_payload = link.split("://")
        payload = base64.b64decode(encoded_payload.encode("ascii")).decode("utf-8")
        node = json.loads(payload)
        node["ps"] = re.sub(DOMAIN_REGEX, "EasyV2raySub", node["ps"])
        encoded_node = base64.b64encode(json.dumps(node).encode("utf-8")).decode("ascii")
        return scheme + "://" + encoded_node
    except Exception:
        return link


def build_subscription(links: Sequence[str]) -> str:
    renamed_links = [_replace_node_name(link) for link in links]
    return base64.b64encode("\n".join(renamed_links).encode("utf-8")).decode("ascii")


def write_subscription(links: Sequence[str], output_path: str | Path) -> None:
    atomic_write_text(output_path, build_subscription(links))
