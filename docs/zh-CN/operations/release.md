# 发布验收

版本权威为 pyproject.toml。运行 `python scripts/release/version.py --check` 以及 `python scripts/ci/generate_interfaces.py --check`，保留精确逐文件 inventory。

先用 `scripts/release/build_release.py` 从精确提交构建源码和 wheel。维护者通过 `scripts/release/fetch_portable_inputs.py` 下载仓库固定摘要的运行时和核心，并准备 CPython 3.12 / manylinux2014_x86_64 的完整 Textual wheelhouse。`scripts/release/build_portable_bundle.py` 只读取这些本地输入，产出完整目录包与 SHA256；许可证及核心源码链接随包提供。运行时版本在 portable-runtime.json 中固定。

CI 在 Ubuntu 22.04 与 24.04 中运行完整回归、核心测试、旧格式安装与迁移，以及完整包断网验收。`scripts/release/verify_portable_bundle.py --real-users --require-isolation --ssh-user USER` 必须在 `unshare --mount --net` 的一次性命名空间以 root 启动；USER 为已有普通账号，内部用两个不同 UID 测试并发实例、权限和认证、节点选择持久化、真实 SSH/PTY 中文输入、键盘及缩放、界面打开时拒绝升级、无系统 Python 的安装/更新及无历史残留，并记录包大小、安装占用、启动耗时和界面 RSS。测试不创建系统账号或修改现有服务。

release gate 必须同时检查两个系统的完整包报告及一致的完整包 SHA256。`--worktree` 产物标记 publishable:false，仅供开发，不可发布。正式发布前保留旧业务和安全回归，历史回滚断言已替换为当前版本保留和失败恢复断言。

## 发布已验收的提交

1. 审阅全部中英文当前文档，为旧版说明标注历史版本。修改 pyproject.toml，执行 `python scripts/release/version.py --sync`，更新 Changelog、稳定版本标记，并检查版本、文档、生成参考及精确文件清单。组件许可文件必须随实现一起提交。
2. 推送已审阅的提交，要求 `.github/workflows/test.yml` 的全部任务及 `release-gate` 成功。两个 Ubuntu 任务必须验收同一提交。不要使用工作区开发包，也不要用验收后本地重建的文件替换产物。
3. 下载两个 `release-candidate-ubuntu-*`、两个 `validation-ubuntu-*` 和 `release-gate` 产物。源码、wheel 和完整包采用 Ubuntu 22.04 的候选；各 Ubuntu 离线套件取对应目标的候选。核对 build receipt 的普通产物摘要、套件与摘要配对、门禁的提交/版本及完整资产清单，拒绝重复、缺失或不一致文件。
4. 将两个验收目录中原样的 JSON 报告汇总为 `validation-evidence.json`，与 `release-gate.json` 及门禁列出的全部资产一起发布。标签必须指向已验收的完整提交。发布说明写明不保留历史版本/备份、旧安装迁移方式、目标系统及组件许可；全部必检项通过后才标记为最新稳定版。
5. 查询公开发布和标签，重新下载交付的摘要、元数据与完整包，与门禁产物比较，并检查版本发现。记录发布链接与 CI 链接，不覆盖旧版本的标签或资产。

完整包使用独立 `.tar.gz.sha256`；`SHA256SUMS` 仅涵盖普通源码和 wheel 资产，各旧式离线套件也有独立摘要。build receipt 绑定源码/wheel 摘要与提交，release gate 记录通过验收的资产名称。同一渠道的元数据及摘要不等于独立签名。
