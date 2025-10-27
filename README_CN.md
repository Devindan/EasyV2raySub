[English](README.md) | 简体中文

# EasyV2RaySub

简单的方法生成你自己的V2Ray订阅链接。

# 使用

许多免费的V2Ray服务提供方并不提供订阅链接，所以当其每次更新的时候，你都必须要手动去复制服务节点的链接。而更新有时候又非常频繁，导致手动复制非常繁琐。\
这个项目可以帮助你生成一个订阅链接，来摆脱上述困扰。

# 指南

## 使用GitHub工作流（Workflow)

### 1. 在GitHub上Fork这个项目

### 2. 编辑工作流配置

工作流的配置文件为`.github/workflows/generate.yml`.\
将其中的`YOUR_URL_HERE`替换成你自己的URL（即包含免费节点链接的网址）:

```yaml
- name: Run generate.py
  run: python generate.py --url YOUR_URL_HERE
```

### 3. 执行工作流任务

可以在你fork之后项目的`Actions`部分，查看工作流任务的状态和详情。你也可以在这里手动执行任务。\
在默认设置下，工作流任务每2小时自动执行一次。如果想要修改执行频率，可以编辑配置文件中定时任务配置的`cron`部分：

```yaml
on:
  schedule:
    - cron: '0 */2 * * *' # 例如，将2修改为12，代表每12小时执行一次工作流任务。
```

定时任务配置使用`cron`
语法，可以在[cron表达式](https://baike.baidu.com/item/cron/10952601?fromModule=search-result_lemma-recommend#3)查看详情。

### 4. 获取你的订阅链接

使用文件`links.txt`的链接作为你的**订阅链接**。它应该是这样的形式：

```text
https://raw.githubusercontent.com/你的用户名/你的项目名/main/links.txt
```

## 使用私有服务器

### 1. 准备python环境

依赖版本:

- python >= 3.11
- requests >= 2.32.3
- beautifulsoup4 >= 4.12.3

### 2. 执行脚本

使用你自己的URL运行脚本:

```shell
python generate.py --url YOUR_URL_HERE
```

执行后脚本会在项目根目录下输出一个名为`links.txt`的文件。\
可以使用`-h`参数查看更多信息:

```shell
python generate.py -h
```

### 3. 生成链接

使用任意工具，例如Nginx，从你的服务器上生成一个链接映射到`links.txt`文件。这个链接即可作为你的**订阅链接**使用。

# 原理

这个项目使用了简单的正则表达式（你也可以添加自己的）来匹配指定网页中，带有`hysteria2`、`vmess://`、`vless://`和`ss://`协议头的链接。

当链接被提取出来后，这些链接将会以[2dust/v2rayN](https://github.com/2dust/v2rayN/wiki/%E8%AE%A2%E9%98%85%E5%8A%9F%E8%83%BD%E8%AF%B4%E6%98%8E)
中定义的格式写入`links.txt`文件，即：

- 所有的链接使用分割符`\n`拼接成一个字符串，然后使用`Base64`进行编码。

之后，文件`links.txt`的URL即可用作V2Ray客户端的**订阅链接**。