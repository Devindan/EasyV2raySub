[English](README.md) | 简体中文

# EasyV2RaySub

EasyV2RaySub 只抓取一次一个或多个网页，再用同一份保持顺序且已去重的代理 URI 列表生成两个输出：

- `links.txt`：供 [v2rayN](https://github.com/2dust/v2rayN/wiki/%E8%AE%A2%E9%98%85%E5%8A%9F%E8%83%BD%E8%AF%B4%E6%98%8E) 使用的 Base64 订阅。
- `sing-box_config.json`：供 Android 版 sing-box（SFA）作为远程配置使用的完整配置文件。

生成的配置以 SFA/core `1.14.0-beta4` 为目标版本，并已使用该版本验证。由于模板使用了 1.14 配置字段，sing-box/SFA `1.13` 及更早版本不兼容。

两个输出来自同一次抓取，因此对应同一个来源快照。主 GitHub 工作流通过一条命令生成它们，并在同一个提交中更新它们。

## 支持的协议

支持七个协议族：
- VMess（`vmess://`）
- VLESS（`vless://`）
- Trojan（`trojan://`）
- Shadowsocks（`ss://`）
- Hysteria 2（`hy2://` 或 `hysteria2://`）
- TUIC（`tuic://`）
- AnyTLS（`anytls://`）

单个无效 URI 不会写入 sing-box 代理出站。包含 `plugin` 参数的 Shadowsocks URI 会被拒绝，因为当前不支持转换插件配置。


## GitHub Actions

1. Fork 本仓库。
2. 编辑 `.github/workflows/generate.yml` 中的来源 URL。
3. 在仓库的 **Actions** 页面运行 **Generate V2Ray Links**，或者等待默认每两小时执行一次的定时任务。
4. 使用你的 fork 中两个文件的 Raw 地址：

```text
https://raw.githubusercontent.com/{你的用户名}/{你的项目名}/main/links.txt
https://raw.githubusercontent.com/{你的用户名}/{你的项目名}/main/sing-box_config.json
```

定时任务采用 cron 语法。例如，把 `0 */2 * * *` 改为 `0 */12 * * *`，即可每 12 小时运行一次。

另外两个工作流只生成 `links2.txt` 和 `links3.txt`。它们显式传入 `--skip-singbox`，因此不会替换主 sing-box 配置。

## 本地或私有服务器用法

建议使用 Python 3.11 或更高版本。通过依赖文件安装依赖，避免在 shell 命令中直接使用未加引号的版本约束：

```shell
python -m pip install -r requirements.txt
```

从一个或多个来源网页一次生成两个输出：

```shell
python generate.py --url 你的URL --output-file links.txt --singbox-template sing-box_template.json --singbox-output sing-box_config.json
```

可以使用 Nginx 等静态文件服务器发布输出。`links.txt` 的 URL 是 v2rayN 订阅地址；`sing-box_config.json` 的 URL 是 SFA 远程配置地址。

### 在 SFA 中添加远程配置

1. 用稳定的 HTTPS URL 发布 `sing-box_config.json`，例如上面的 GitHub Raw 地址。
2. 在 Android 的 SFA 中打开**配置（Profiles）**，点击 **+**，新建**远程（Remote）**配置并粘贴该 URL。
3. 保存并刷新配置，选择它，然后启动服务。

请使用本项目目标并已验证的 SFA/core `1.14.0-beta4`。sing-box/SFA `1.13` 及更早版本无法导入该模板，因为模板使用了 1.14 配置字段。

生成文件以 `sing-box_template.json` 为模板；该模板提供 Android TUN、DNS、选择器、URL 测试和路由配置，脚本负责填入生成的代理出站。

## 命令行参数

| 参数 | 必填/默认值 | 说明 |
| --- | --- | --- |
| `-h`、`--help` | 可选 | 显示帮助信息并退出。 |
| `-u`、`--url`、`--urls` | 必填；无默认值 | 一个或多个来源 URL。三种写法互为别名，都可接收一个或多个值。 |
| `-ar`、`--additional-regex` | 可选；默认：未设置 | 增加一个正则表达式，其匹配结果会追加到提取出的 URI 列表。 |
| `-o`、`--output-file` | 可选；默认：`links.txt` | v2rayN 订阅输出路径。 |
| `--singbox-template` | 可选；默认：`sing-box_template.json` | 静态 sing-box JSON 模板的输入路径。 |
| `--singbox-output` | 可选；默认：`sing-box_config.json` | 生成的 sing-box 配置输出路径。 |
| `--skip-singbox` | 可选；默认：false | 只生成 v2rayN 订阅。 |

运行 `python generate.py -h` 可查看 CLI 帮助。

## 失败行为

当所有来源均失败，或者没有提取到任何代理链接时，命令以状态码 1 退出。

启用 sing-box 生成时，如果没有任何提取出的 URI 能转换成有效的 sing-box 出站、模板不存在或模板 JSON 无效，也会以状态码 1 退出。

程序会把这些已知错误写到标准错误，并且不替换两个已有输出，避免失败任务发布空文件或只更新其中一个文件。

如果某个来源失败，但其他来源成功返回链接，程序会继续使用成功来源生成输出。

## 测试

运行完整测试套件：

```shell
python -m unittest discover -s tests -v
```
