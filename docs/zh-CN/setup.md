# 安装并初始化 Mihomo

先完成 [控制层安装与发布包核验](../../INSTALL.md)。要求 Linux 与 Python 3.10+；安装器不下载核心、不改 Shell 启动文件。当前终端临时加入 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl version
```

## 复用已有核心

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

支持的 Linux 架构可使用仓库内维护的固定摘要；只有显式执行才下载：

```bash
mihomoctl core install --version v1.19.32
mihomoctl core list
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
```

没有 manager 时 `core install` 仅保存核验后的核心，需要按示例明确 init；已有 manager 时会通过受保护事务激活新核心。其他版本须用 `--sha256` 提供独立核验过的压缩包摘要；未知版本没有摘要会拒绝。摘要匹配不代表上游签名验证或可复现构建。

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
