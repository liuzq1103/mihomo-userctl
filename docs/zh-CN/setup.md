# 安装并初始化 Mihomo

完整新装按“控制器与依赖 → 可信 Mihomo 核心 → 初始化 → 配置验证”完成，默认到此结束，不启动运行时。先完成 [控制层安装与发布包核验](../../INSTALL.md)；交给 Agent 可使用 [本地安装 prompt](agent-local-install-prompt.md)。要求 Linux 与 Python 3.10+。`install.sh` 仍只安装控制器，不下载核心、不改 Shell 启动文件；核心安装与初始化是下面的显式步骤。当前终端临时加入 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl version
```

## 复用已有核心

先检查 `${XDG_CONFIG_HOME:-$HOME/.config}/mihomoctl/manager.yaml`（自定义配置目录时使用实际路径）。已有 manager 时只检查并保留，不重复 init、不主动 core install；缺失或损坏的配置核心属于修复任务，先报告具体阻塞。没有 manager 时，按以下两条路径选择其一。

核心须为绝对路径、可执行、由本人或 root 拥有，且不能被组或其他用户写入。初始化会验证副本，保留原始配置和核心：

```bash
mihomoctl init --core /absolute/path/to/mihomo
```

如果需要导入已有配置，改为只执行下面一次初始化：

```bash
mihomoctl init --core /absolute/path/to/mihomo --config /absolute/path/to/config.yaml
```

不要在已有 manager 上重复 init。导入会保留路由策略；初始化后检查私有活动配置和 listener 认证。

## 显式安装固定版本核心

没有可信现有核心且允许联网的新装，默认使用 **v1.19.32**，不要求用户另选版本；这是项目固定测试版本，不表示上游最新版。仓库摘要目前只覆盖 Linux **x86_64 / amd64-compatible**。在该架构执行：

```bash
mihomoctl core install --version v1.19.32
mihomoctl core list
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
mihomoctl config validate
```

没有 manager 时 `core install` 仅保存核验后的核心，需要按示例明确 init。**已有 manager 时，它会激活新核心，并可能停止、重启正在运行的旧核心**；不要把上述新装步骤用于升级已有运行时。arm64/armv7 即使选择同一版本，也需要对应资产经核验的 `--sha256` 或可信本地核心；其他版本同样需要摘要。不要绕过校验。摘要匹配不代表上游签名验证或可复现构建。

本地安装包不包含 Mihomo，也不代表目标必须离线。允许联网时，以上显式核心下载属于完整新装；严格离线时需提前准备可信核心，缺少时在安装前报告，不能承诺完整离线初始化。核心下载需要可用的直连或已有可信代理环境；不要用尚未初始化、未启动的自身 `mihomoctl exec` 引导下载自身核心。

安装验收分别报告控制器核验、核心版本和配置验证。默认未启动时，运行态健康与远端代理均标为 UNVERIFIED；需要继续使用时再执行下一节。默认 `MATCH,DIRECT` 不能提供远端代理。

## 启动与实际路径

```bash
mihomoctl config validate
mihomoctl start
mihomoctl status
mihomoctl health check
```

默认 user/process，不需要 root 或 systemd；init 不启动进程。修改配置后先验证，再显式 restart。可选 `service install` 切换到受管 systemd 后端，但不会 enable 或启动。system 作用域必须前置明确的 `--system` 并由管理员执行，工具不会调用 sudo。

| 用途 | 用户路径（XDG 默认值） |
| --- | --- |
| Manager | `$XDG_CONFIG_HOME/mihomoctl/manager.yaml`，默认 `~/.config/mihomoctl/manager.yaml` |
| 活动核心配置 | 默认 `~/.config/mihomoctl/mihomo/config.yaml`，以 manager 的 `core.config` 为准 |
| 凭据 | `~/.config/mihomoctl/profiles/` |
| 核心 HomeDir | `$XDG_DATA_HOME/mihomoctl/core-home`，默认 `~/.local/share/mihomoctl/core-home` |
| 日志与备份 | `$XDG_STATE_HOME/mihomoctl/`，默认 `~/.local/state/mihomoctl/` |
| 缓存 | `$XDG_CACHE_HOME/mihomoctl/`，默认 `~/.cache/mihomoctl/` |
| 运行态 | `$XDG_RUNTIME_DIR/mihomoctl/`；未设置时回退私有 state/runtime |

默认新配置为 `MATCH,DIRECT`。接下来依次阅读 [订阅](subscriptions.md)、[规则](rules.md)、[实际验证](first-run.md)。
