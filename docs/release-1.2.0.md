# 1.2.0 release notes / 发布说明

Adds official stable-release discovery, verified acquisition and one-command
upgrades: `mihomoctl release check`, `mihomoctl release fetch --output-dir DIR`,
and `mihomoctl update --latest`.

新增官方稳定版本发现、核验后发行获取及单条命令升级。交互式 status、version、doctor
和 TUI 的自动检查限频后台运行，后续入口对同一版本只提示一次；失败不改原命令退出码。
显式联网失败返回 2 / UNVERIFIED，不宣称当前已是最新版本。

**v1.0.0–v1.1.1 用户必须继续使用核验后的 1.2.0 安装器升级。** 旧二进制无法自行获得
通知或新命令。1.1.1 修复的订阅策略失效开放问题也不能依靠旧版本自动发现。

**Existing v1.0.0–v1.1.1 users must use the verified 1.2.0 installer.** Old
binaries cannot acquire notifications or these commands themselves. The silent
subscription-policy defect fixed in 1.1.1 is another reason to retain installer
instructions independently of optional notifications.

Portable acquisition supports the existing Ubuntu 22.04/Python 3.10 and Ubuntu
24.04/Python 3.12 x86_64 offline kits. Transfer the entire acquired directory and
use its verified source installer offline. Normal acquisition does not include
dependencies. See [English update guide](en/update.md) / [中文升级说明](zh-CN/update.md).

Existing local update semantics, installation gates, private backups and
self-contained rollback remain in force. Configuration, subscriptions,
credentials, existing caches and Mihomo cores are preserved. No process is
restarted. No cron, shell startup file, automatic elevation, global proxy or
implicit core installation is introduced. Checksums, receipts and gate records
are consistency evidence, not independent publisher signatures.
