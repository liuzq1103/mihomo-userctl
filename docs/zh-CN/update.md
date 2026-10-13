# 升级与回滚

按 [INSTALL.md](../../INSTALL.md) 使用核验后的 **1.1.0 安装器** 升级 v1.0.x。旧 updater 可能因期待已移除的 Bash 版本标记而拒绝新目录结构；不要添加垫片或绕过检查。使用完整核验的新版发布树，根据需要提供依赖 wheelhouse 和明确的解释器。

安装产生私有备份并报告路径，仅切换代码/launcher，不重启 Mihomo 或应用。检查安装版本，用新版安装器的 `scripts/bootstrap.py verify` 核验。确认前保留备份。需要恢复时执行自包含备份驱动：

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

驱动自带恢复引擎，无需原始源码。用户配置、凭据、订阅、缓存、核心保持完整。更新必须通过协议、版本、源码/wheel 清单、依赖和私有路径校验。后续兼容更新可先用 `mihomoctl update SOURCE --dry-run` 预览；未经核验的 checkout 不是正式发行版。
