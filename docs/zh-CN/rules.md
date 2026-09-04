# 私有自定义规则

[English](../en/rules.md) · [文档索引](README.md) · [安装配置](setup.md)

`mihomo-userctl` 将个人路由策略与公共项目分离。控制器只检查本文约定的布局，不创建规则文件、不改写 `config.yaml`、不重启 Mihomo，也不上传任何策略数据。

## 布局与权限

在 `mihomo -d` 使用的 Mihomo HomeDir 下放置三个文件：

```text
<Mihomo HomeDir>/rules/custom-direct.yaml
<Mihomo HomeDir>/rules/custom-proxy.yaml
<Mihomo HomeDir>/rules/custom-reject.yaml
```

`rules` 目录必须由当前用户所有且权限为 `700`；三个文件必须是当前用户所有、权限 `600` 的普通文件，不能是符号链接。可从 `examples/rules/` 的虚构示例开始，但不要把真实个人规则提交到本仓库。

每个文件使用 Mihomo classical provider 格式：

```yaml
payload:
  - DOMAIN-SUFFIX,example.com
```

在 `config.yaml` 中使用以下固定 provider 契约：

```yaml
rule-providers:
  custom-direct:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-direct.yaml
  custom-proxy:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-proxy.yaml
  custom-reject:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-reject.yaml
```

对应规则必须位于最终 fallback 之前：

```yaml
rules:
  - RULE-SET,custom-direct,DIRECT
  - RULE-SET,custom-proxy,Proxy
  - RULE-SET,custom-reject,REJECT
  - MATCH,DIRECT
```

`Proxy` 必须是现有策略组；`DIRECT` 和 `REJECT` 是 Mihomo 内置策略。Mihomo 从上到下匹配，若 `MATCH` 在前，后面的自定义规则不会生效。

## 只读命令

```bash
mihomoctl rules status
mihomoctl rules status --json
mihomoctl rules check
```

默认路径为 `${XDG_DATA_HOME:-$HOME/.local/share}/mihomo` 和 `${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/config.yaml`。服务使用其他位置时必须显式给出两个绝对路径，不能让工具猜测：

```bash
mihomoctl rules check --home-dir /absolute/mihomo-home --config /absolute/config.yaml
```

`status` 只报告文件名、规则数、SHA-256、修改时间和权限状态，不输出规则原文。`check` 还会核对 provider 引用、目标策略、顺序，并调用已安装的 Mihomo 执行 `-t`。Mihomo 的原始输出会被抑制，因为任意配置错误可能包含私有值。

结构检查只支持本文约定的 block-style 相关段落。锚点、merge、flow mapping 或其他无法可靠分类的形式返回 `2`；只需把自定义 provider 相关段落改写为本文形式后重试。缺少最终 `MATCH` 仅报告警告，因为 fallback 应由用户自己决定。

退出 `0` 表示所有必需检查通过，可能同时含 fallback 警告；`1` 表示实际观察到文件、provider、目标、顺序或 Mihomo 配置失败；`2` 表示参数、路径、依赖错误，或结构无法可靠验证。

修改个人规则前，应在私有位置备份三个规则文件和 `config.yaml`。编辑后运行 `mihomoctl rules check`；是否重启 Mihomo 是另一项显式操作。验证失败时恢复备份并再次检查。
