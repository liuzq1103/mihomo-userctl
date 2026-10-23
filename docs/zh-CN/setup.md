# 安装并初始化 Mihomo

完整包用户直接运行 `mihomoctl`，按[终端教程](console.md)完成向导：解释器、界面依赖与固定核心都已内置，无需系统 Python 或虚拟环境。订阅预览后确认保存并启动。下列显式 CLI 步骤是已准备 Linux/Python 3.10+ 环境时的高级兼容路径；单独安装与 init 默认不启动核心。先见[安装与核验](../../INSTALL.md)。当前终端临时加入 PATH：

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

## 恢复到默认配置

订阅、规则和探测设置都是在 `init` 生成的配置之上逐项叠加的，没有整体重写的入口；`init` 在 `manager.yaml` 已存在时也会拒绝重复执行。`reset` 是显式的一次性回退：先预览，再用 `restart` 让它生效。

```bash
mihomoctl reset --dry-run
mihomoctl reset --apply
mihomoctl config validate
mihomoctl restart
```

预览和执行使用同一份待移除清单。`reset --apply` 会停止运行时，通过事务删除 manager 配置、活动核心配置、全部 `profiles/*.yaml` 凭据以及遗留的 `.before-policy-*` 备份和 `.userctl-state.json` 回执，然后用与 `init` 完全相同的默认形态重新发布（随机端口、随机密钥、`MATCH,DIRECT`）。恢复材料仅在操作未完成时临时存在，成功后删除；`mihomoctl reset --core PATH` 可以改用另一个核心重新初始化。

被重置的是配置，不是安装：Mihomo 核心二进制、订阅 preview 缓存和日志都会保留。凭据与 controller secret 会重新生成，旧凭据立即失效，之前导出的环境文件需要重新导出。`reset` 不触碰订阅，导入完成后自行重新执行 [订阅](subscriptions.md) 的 preview/apply。

## 显式安装固定版本核心

没有可信现有核心且允许联网的新装，默认使用 **v1.19.32**，不要求用户另选版本；这是项目固定测试版本，不表示上游最新版。仓库摘要目前只覆盖 Linux **x86_64 / amd64-compatible**。在该架构执行：

```bash
mihomoctl core install --version v1.19.32
mihomoctl core list
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
mihomoctl config validate
```

没有 manager 时 `core install` 仅保存核验后的核心，需要按示例明确 init。**已有 manager 时，它会激活新核心，并可能停止、重启正在运行的旧核心**；不要把上述新装步骤用于升级已有运行时。arm64/armv7 即使选择同一版本，也需要对应资产经核验的 `--sha256` 或可信本地核心；其他版本同样需要摘要。不要绕过校验。摘要匹配不代表上游签名验证或可复现构建。

源码、wheel 和旧式 Python 套件不包含 Mihomo；推荐的 SSH 完整包已内置固定核心。目标不必离线。允许联网时，以上显式核心下载属于完整新装；严格离线时需提前准备可信核心，缺少时在安装前报告，不能承诺完整离线初始化。核心下载需要可用的直连或已有可信代理环境；不要用尚未初始化、未启动的自身 `mihomoctl exec` 引导下载自身核心。

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
| 日志与未完成恢复 | `$XDG_STATE_HOME/mihomoctl/`，默认 `~/.local/state/mihomoctl/` |
| 缓存 | `$XDG_CACHE_HOME/mihomoctl/`，默认 `~/.cache/mihomoctl/` |
| 运行态 | `$XDG_RUNTIME_DIR/mihomoctl/`；未设置时回退私有 state/runtime |

默认新配置为 `MATCH,DIRECT`。接下来依次阅读 [订阅](subscriptions.md)、[规则](rules.md)、[实际验证](first-run.md)。
