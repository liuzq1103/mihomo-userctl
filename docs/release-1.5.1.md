# 1.5.1 release notes / 发布说明

This patch fixes two Textual interface defects: all five Chinese subscription-policy labels remain visible in expanded lists, including compact and odd-width terminals; queued navigation events no longer bounce between pages. Buttons, shortcuts, legacy page aliases and the pinned Textual version remain unchanged.

本补丁修复两项 Textual 界面问题：展开列表完整显示五个中文订阅策略标签，覆盖紧凑和奇数列宽终端；过期导航事件不再导致页面来回跳转。保留按钮、快捷键、历史页面别名及固定 Textual 版本。

Complete Linux x86_64 bundles and acceptance tests now use Mihomo v1.19.33, verified against the official release asset digest. The reviewed v1.19.32 pin remains available for explicit installation. Updating mihomoctl does not automatically replace an existing user's core. Core environment isolation, authentication, ownership checks, transaction recovery and current-only retention remain unchanged.

Linux x86_64 完整包与验收测试的固定核心升级为 Mihomo v1.19.33，并核对官方发行资产摘要。保留已审核的 v1.19.32 固定摘要供显式安装。升级 mihomoctl 不会自动替换用户现有核心；核心环境隔离、认证、属主检查、事务恢复及仅保留当前版本的策略保持不变。

Python installations should upgrade through their original package manager; complete installations use the managed updater. The CLI and import package remain `mihomoctl`, and the distribution remains `mihomo-userctl`. Users migrating from 1.4.x must still verify and run the new complete bundle's installer because the old updater cannot discover renamed assets. See [Python installation](en/python-install.md), [offline installation](en/offline-install.md), [中文 Python 安装](zh-CN/python-install.md) and [中文离线安装](zh-CN/offline-install.md).

Python 安装由原包管理器升级，完整安装使用受管更新器。CLI 与 import 包保持 `mihomoctl`，分发包保持 `mihomo-userctl`。从 1.4.x 迁移仍须核验并运行新版完整包安装器，因为旧更新器无法发现改名资产，详见上述双语安装指南。

Publication uses exact-commit two-Ubuntu acceptance, reviewed inventories and independent reviews of the candidate SHA and actual draft hashes. PyPI receives the same accepted wheel and sdist through manual Trusted Publishing. This patch does not add headless bundle-core preparation or change subscription-validation timeouts.

发布沿用同提交双 Ubuntu 验收、审核文件清单及对候选 SHA 和实际草稿摘要的独立复核。PyPI 通过手动 Trusted Publishing 上传同批验收的 wheel 与 sdist。本补丁不新增 headless 随包核心准备命令，也不修改订阅配置校验超时。
