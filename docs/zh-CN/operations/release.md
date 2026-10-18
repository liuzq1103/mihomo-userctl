# 发布运维与验收

在专用分支实施。私有本地文件不得进入 Git 或精确发布清单。当前运行时位于 mihomoctl/；legacy/v0.9/ 仅保存历史源码。发布工具位于 scripts/release/，检查工具位于 scripts/ci/。

版本权威是 pyproject.toml。修改后执行 `python scripts/release/version.py --sync`，审阅更新最新 Changelog 以及 README.md、README.en.md、INSTALL.md 的 stable-version 标记，再执行 `python scripts/release/version.py --check`。历史版本不改写。生成的命令参考和补全必须通过 `python scripts/ci/generate_interfaces.py --check`。

CI 必须同时通过 Ubuntu 22.04/Python 3.10 和 Ubuntu 24.04/Python 3.12：完整单元、Controller 和 TUI 回归，文档与秘密门禁，固定核心真实测试，真实用户/systemd/隔离 TUN，精确提交的源码与 wheel 安装、更新、自包含回滚，以及两种套件的断网离线验收。另须从真实 v1.0.3 安装升级并回滚，检查用户数据完整。必需套件跳过不能认定成功。

`python scripts/release/build_release.py` 从选定 Git 提交读取版本，交叉核验运行时、manifest、文档及 wheel 元数据，严格执行逐文件清单，生成源码包、wheel、SHA256SUMS 和绑定提交的 receipt。--worktree 输出仅用于开发，不能发布。`python scripts/release/verify_release.py --help` 列出证据输入；最终提交门禁必须返回 verified: true。

通过 PR 合并；main 最终提交取得完整门禁后才能创建下一次发行标签，不移动或替换已经发布的标签。核对新标签提交，再核验标签 CI，只上传该提交的源码 tar.gz/zip、wheel、两种离线套件、摘要、receipt 与门禁证据。当前 v1.0.x 使用核验后的 v1.2.0 安装器升级。未观察真实 Codex 请求时仍记录 UNVERIFIED，不能用 CI 代理探测推断。

文档修复同样经过 PR、审查与 CI，但不要求发布新版本。更新 main 不会改写用户已下载包内的文档；继续遵守源码/归档信任校验，并参考当前 [本地安装 prompt](../agent-local-install-prompt.md) 和 [离线包布局](../offline-install.md)。未来套件 README 须说明控制层包内容、显式核心/初始化步骤、严格离线前提及默认不启动。
