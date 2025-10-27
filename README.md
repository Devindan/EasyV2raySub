English | [简体中文](README_CN.md)

# EasyV2RaySub

Easy way to generate your own V2Ray subscription link.

# Usage

Many free V2Ray server providers do not provide subscription link, so you have to manually copy the server link every
time it is updated. Unfortunately, these updates can sometimes be very frequent, which can be annoying.\
This project can help you generate a subscription link to get rid of this problem.

# Instructions

## With GitHub Workflow

### 1. Fork this project on GitHub

### 2. Edit the workflow configuration

The workflow configuration file is `.github/workflows/generate.yml`.\
Replace `YOUR_URL_HERE` with your desired URL, which is the website that contains free V2Ray server links:

```yaml
- name: Run generate.py
  run: python generate.py --url YOUR_URL_HERE
```

### 3. Execute the workflow job

Check the workflow job status and details in your project's `Actions` section. You can also manually trigger the job
here.\
By default, it runs automatically every 2 hours. To change the frequency, edit the `cron` schedule in the configuration
file:

```yaml
on:
  schedule:
    - cron: '0 */2 * * *' # For example, changing 2 to 12 means running the workflow job every 12 hours.
```

The schedule uses cron syntax, see [cron expression](https://en.wikipedia.org/wiki/Cron#Cron_expression) for details.

### 4. Get your subscription link

Use the link of the `links.txt` file as your **Subscription Link**. It will look like:

```text
https://raw.githubusercontent.com/{YOUR_USERNAME}/{YOUR_PROJECT_NAME}/main/links.txt
```

## With Private Server

### 1. Prepare the python environment

Requirements:

- python >= 3.11
- requests >= 2.32.3
- beautifulsoup4 >= 4.12.3

### 2. Execute the script

Run the script with your own URL:

```shell
python generate.py --url YOUR_URL_HERE
```

This will output a file named `links.txt` in the root directory.\
For more information, use `-h`:

```shell
python generate.py -h
```

### 3. Generate the link

Use any tool, such as Nginx, to serve the `links.txt` file from your server. Use this URL as your **subscription
link**.

# How it works?

This project uses simple regex (you can also add your own) to match links with the protocol
prefixes `hysteria2`, `vmess://`, `vless://` and `ss://` from a specific website.

Once the links are extracted, they are written into the `links.txt` file in the format specified
by [2dust/v2rayN](https://github.com/2dust/v2rayN/wiki/%E8%AE%A2%E9%98%85%E5%8A%9F%E8%83%BD%E8%AF%B4%E6%98%8E), which
states:

- All links are joined into a string with delimiter `\n`, then encoded into `Base64`.

The URL of the `links.txt` file can then be used as a **subscription link** for V2Ray clients.