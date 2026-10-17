# 升级与回滚

## 已安装 1.2.0 及后续兼容版本

```bash
mihomoctl release check
mihomoctl update --latest --dry-run
mihomoctl update --latest
```

检查只报告本次观察到的官方稳定发行，不断言当前已是最新。自动通知仅在交互式 status、version、doctor 和 TUI 入口限频触发，后台进程五秒内退出，下一次入口显示缓存结果；同一作用域同一版本只提示一次。自动失败不改原命令退出码；显式联网命令失败返回 2 / UNVERIFIED。可用 `MIHOMOCTL_NO_UPDATE_CHECK=1` 禁用自动检查。JSON、管道和其他命令不触发查询。

`update --latest` 固定一次查询得到的版本，取得发行物并校验后交给原离线安装器。在两个支持的 Ubuntu 目标上优先使用完整套件；显式 `--wheelhouse` 使用普通发行和指定依赖。其他环境由安装器核验已有依赖，缺失时提供本地 wheelhouse，不自动访问 PyPI。dry-run 会联网取得及校验文件，但不切换安装。`SOURCE` 与 `--latest` 互斥，无参数 update 仍拒绝；`mihomoctl update SOURCE` 保持纯离线。

## 跨机器取得发行物

```bash
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target ubuntu22.04-x86_64-py310
```

另一个目标是 `ubuntu24.04-x86_64-py312`，选择目标机器的环境。命令只取得并校验，不安装；可用 `--version v1.2.0` 固定版本。不指定 target 时取得普通源码包、wheel、摘要、receipt 和门禁证据，不包含依赖。目录必须不存在；失败不发布半成品，不覆盖已有文件。

将整个输出目录传到目标机器本人拥有的私有目录。源码包位于 `kit/release/`，依赖在 `kit/wheelhouse/`，acquisition.json 记录相对路径。在离线机器解包源码，再运行包内新版 install.sh；已有兼容 CLI 也可把源码包路径传给 `update SOURCE --wheelhouse DIR`。见 [离线安装](offline-install.md)。

v1.0.0–v1.1.1 没有这些新命令和通知能力，请按下面的新版安装器路径升级；通知不是唯一信息渠道。

按 [INSTALL.md](../../INSTALL.md) 使用核验后的 **1.2.0 安装器** 升级 v1.0.x。旧 updater 可能因期待已移除的 Bash 版本标记而拒绝新目录结构；不要添加垫片或绕过检查。使用完整核验的新版发布树，根据需要提供依赖 wheelhouse 和明确的解释器。

安装产生私有备份并报告路径，仅切换代码/launcher，不重启 Mihomo 或应用。检查安装版本，用新版安装器的 `scripts/bootstrap.py verify` 核验。确认前保留备份。需要恢复时执行自包含备份驱动：

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

驱动自带恢复引擎，无需原始源码。用户配置、凭据、订阅、缓存、核心保持完整。更新必须通过协议、版本、源码/wheel 清单、依赖和私有路径校验。后续兼容更新可先用 `mihomoctl update SOURCE --dry-run` 预览；未经核验的 checkout 不是正式发行版。
