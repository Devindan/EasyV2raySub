import argparse
import json
import os
import sys
from pathlib import Path

from crawler import NoLinksError, crawl_links
from file_utils import atomic_write_text
from singbox_convertor import NoValidOutboundsError, build_singbox_config
from v2ray_subscription import build_subscription


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-u",
        "--url",
        "--urls",
        dest="urls",
        required=True,
        nargs="+",
        help="One or more websites containing supported proxy links.",
    )
    parser.add_argument(
        "-ar",
        "--additional-regex",
        help="Add another regular expression used to match links.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        default="links.txt",
        help="Write the v2rayN subscription to this file.",
    )
    parser.add_argument(
        "--singbox-template",
        default="sing-box_template.json",
        help="Read the static sing-box configuration from this JSON template.",
    )
    parser.add_argument(
        "--singbox-output",
        default="sing-box_config.json",
        help="Write the generated sing-box configuration to this file.",
    )
    parser.add_argument(
        "--skip-singbox",
        action="store_true",
        help="Only generate the v2rayN subscription.",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    if not args.skip_singbox:
        paths = (
            args.output_file,
            args.singbox_template,
            args.singbox_output,
        )
        normalized_paths = {
            os.path.normcase(str(Path(path).resolve(strict=False))) for path in paths
        }
        if len(normalized_paths) != len(paths):
            print(
                "Generation failed: outputs and template must use different paths.",
                file=sys.stderr,
            )
            return 1

    try:
        links = crawl_links(args.urls, args.additional_regex)
    except NoLinksError:
        print("Generation failed: no proxy links were found.", file=sys.stderr)
        return 1

    subscription_content = build_subscription(links)

    singbox_content = None
    if not args.skip_singbox:
        try:
            template_text = Path(args.singbox_template).read_text(encoding="utf-8")
        except FileNotFoundError:
            print("Generation failed: sing-box template not found.", file=sys.stderr)
            return 1

        try:
            template = json.loads(template_text)
        except json.JSONDecodeError:
            print("Generation failed: invalid sing-box template JSON.", file=sys.stderr)
            return 1

        if not isinstance(template, dict):
            print("Generation failed: sing-box template must be an object.", file=sys.stderr)
            return 1

        try:
            config = build_singbox_config(links, template)
        except NoValidOutboundsError:
            print("Generation failed: no valid sing-box outbounds.", file=sys.stderr)
            return 1
        singbox_content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"

    atomic_write_text(args.output_file, subscription_content)
    if singbox_content is not None:
        atomic_write_text(args.singbox_output, singbox_content)

    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
