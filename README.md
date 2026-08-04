English | [简体中文](README_CN.md)

# EasyV2RaySub

EasyV2RaySub crawls one or more pages once and turns the same ordered, deduplicated proxy URI list into two outputs:

- `links.txt`: a Base64-encoded subscription for [v2rayN](https://github.com/2dust/v2rayN/wiki/%E8%AE%A2%E9%98%85%E5%8A%9F%E8%83%BD%E8%AF%B4%E6%98%8E).
- `sing-box_config.json`: a complete configuration for a remote profile in sing-box for Android (SFA).

The generated configuration targets and was validated with SFA/core `1.14.0-beta4`. sing-box/SFA `1.13` and earlier are incompatible because the template uses 1.14 configuration fields.

Generating both outputs from one crawl keeps the two formats on the same source snapshot. The primary GitHub workflow updates them in one command and one commit.

## Supported protocols

The seven supported protocol families are:
- VMess (`vmess://`)
- VLESS (`vless://`)
- Trojan (`trojan://`)
- Shadowsocks (`ss://`)
- Hysteria 2 (`hy2://` or `hysteria2://`)
- TUIC (`tuic://`)
- AnyTLS (`anytls://`)

Invalid individual URIs are omitted from the sing-box proxy outbounds. Shadowsocks URIs containing a `plugin` parameter are rejected because plugin conversion is not supported.

## GitHub Actions

1. Fork this repository.
2. Edit the source URLs in `.github/workflows/generate.yml`.
3. Run **Generate V2Ray Links** from the repository's **Actions** page, or wait for its two-hour schedule.
4. Use the raw files from your fork:

```text
https://raw.githubusercontent.com/{YOUR_USERNAME}/{YOUR_PROJECT_NAME}/main/links.txt
https://raw.githubusercontent.com/{YOUR_USERNAME}/{YOUR_PROJECT_NAME}/main/sing-box_config.json
```

The schedule uses cron syntax. For example, change `0 */2 * * *` to `0 */12 * * *` to run every 12 hours.

The secondary workflows produce `links2.txt` and `links3.txt` only. They explicitly pass `--skip-singbox`, so they do not replace the primary sing-box configuration.

## Local or private-server usage

Python 3.11 or newer is recommended. Install the declared dependencies without putting unquoted version constraints in a shell command:

```shell
python -m pip install -r requirements.txt
```

Generate both outputs from one or more source pages:

```shell
python generate.py --url YOUR_URL_HERE --output-file links.txt --singbox-template sing-box_template.json --singbox-output sing-box_config.json
```

Serve either output with a static file server such as Nginx. `links.txt` is the v2rayN subscription URL. `sing-box_config.json` is the SFA remote-profile URL.

### Add the remote profile to SFA

1. Host `sing-box_config.json` at a stable HTTPS URL, such as its raw GitHub URL above.
2. In SFA on Android, open **Profiles**, tap **+**, choose a new **Remote** profile, and paste the URL.
3. Save the profile, refresh it, select it, and start the service.

Use SFA/core `1.14.0-beta4`, the version targeted and validated here. sing-box/SFA `1.13` and earlier cannot import this template because it uses 1.14 configuration fields.

The generated file is based on `sing-box_template.json`, which supplies the Android TUN, DNS, selector, URL-test, and routing configuration around the generated proxy outbounds.

## Command-line options

| Option | Required/default | Meaning |
| --- | --- | --- |
| `-h`, `--help` | Optional | Show the help message and exit. |
| `-u`, `--url`, `--urls` | Required; no default | One or more source URLs. All three spellings are aliases and accept one or more values. |
| `-ar`, `--additional-regex` | Optional; default: unset | Add a regular expression whose matches are appended to the extracted URI list. |
| `-o`, `--output-file` | Optional; default: `links.txt` | v2rayN subscription output path. |
| `--singbox-template` | Optional; default: `sing-box_template.json` | Input path of the static sing-box JSON template. |
| `--singbox-output` | Optional; default: `sing-box_config.json` | Generated sing-box configuration output path. |
| `--skip-singbox` | Optional; default: false | Generate only the v2rayN subscription. |

Run `python generate.py -h` to view the CLI help.

## Failure behavior

The command exits with status 1 when all sources fail or yield zero proxy links.

When sing-box generation is enabled, it also exits with status 1 if no extracted URI can become a valid sing-box outbound, if the template is missing, or if the template JSON is invalid.

These known failures are reported on standard error and do not replace either existing output, preventing a failed run from publishing an empty or half-updated pair.

If one source fails but another yields links, generation continues with the successful sources.

## Tests

Run the full test suite with:

```shell
python -m unittest discover -s tests -v
```
