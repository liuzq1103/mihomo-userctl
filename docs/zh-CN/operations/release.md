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

## v1.4.3 审核

界面、连接、测速三组修改须由 Claude 配置接入的 GLM 与 MiniMax 独立审核，再交换意见交叉复核；实质整改后重新审核。有效结论须绑定完整候选 SHA，CI 与草稿完成后还须审核实际资产摘要。超时、额度错误、异常协议文本均不算通过，不自动替换审核模型。审核记录独立于提交保存；正式发布仅复用既有双 Ubuntu 门禁的精确资产。

## v1.4.2 历史审核与既有体积门禁

1.4.2 修复要求保留每项任务的真实独立及交叉审核记录。原要求 OpenAI GPT、MiniMax、智谱 GLM 三方审核；MiniMax 渠道额度耗尽后，用户明确授权改为 OpenAI GPT 与智谱 GLM 两方独立审核及交叉复核均通过。保留 MiniMax 既有意见并以代码和测试证据解决，不能将不可用渠道记为通过。两方最终批准必须绑定完整候选提交 SHA；实质变更使旧批准失效。CI 和草稿核验完成后，两方再检查实际 run、草稿资产清单及摘要，操作者才可调度 `publish=true`。绑定 SHA 的最终证据独立于被审提交保存，避免写入 SHA 又改变提交。既有发布器验证 CI 来源和资产身份，不认证模型审核；审核记录与操作者调度门禁是机器检查之外的必要要求。

两个 Ubuntu 任务继续独立构建与完整验收。22.04 上传完整候选；24.04 上传其离线套件、收据及 portable 校验文件，完整报告单独上传。比较收据身份、各环境实装摘要、两份 portable 校验文件和验收摘要。通用 wheel 的 ZIP 字节可因构建环境不同而变化；每个公开资产必须对应实际安装过的产物。

`portable_policy.py` 固定真实 v1.4.0 完整包摘要与提交。网络隔离前使用 `fetch_portable_inputs.py --previous-bundle` 获取。1.5 的独立升级场景由新版完整包安装器完成改名迁移，关闭控制台但保持旧核心运行；旧更新器不能识别新资产名。门禁验证核心 PID、启动时间、路径与摘要、认证、节点选择及受保护文件不变。保留现有 v1.0.x 源码迁移、同版本更新与失败恢复场景。

十进制门槛为下载 65,000,000 字节、解压普通文件 160,000,000 字节、初始化核心后的首次安装逻辑占用 225,000,000 字节。`installed_bytes` 继续表示逻辑大小，目录及 generation 另记录分配块数。安装、初始化和跨版本升级峰值为 home 内每 50ms 采样观测；home 外输入包及验收器临时解压源单独记录。升级峰值不受首次安装门槛约束。

先以成功的 main push 测试 run ID 调度 `publish.yml`，设置 `publish=false`。发布器核验该既有 CI run，重新验证其发布门禁与证据、精确提交/版本及资产名称、大小、摘要，再恢复或创建草稿并下载全部资产逐字节核验；它不重新执行完整 CI 测试矩阵。两方审查实际草稿证据后，以同一 run ID 和 `publish=true` 再次调度。已有 tag 必须对应验收提交，正式资产与说明不得覆盖。公开烟测在隔离 home 验证下载与获取；对于改名资产，先用新版安装器从 v1.4.0 迁移，再验证新版 CLI 的 `update --latest`。公开烟测失败时保留证据并通过后续修复版本处理，不替换已发布文件。

## Python distribution and development candidates

Distribution/new assets use `mihomo-userctl`; import, CLI and XDG paths stay `mihomoctl`. Wheel/sdist names use normalized `mihomo_userctl`. The old pinned upgrade baseline keeps its old name. Standard sdist must rebuild a reviewed wheel outside the checkout. Python installation evidence is required for both Ubuntu targets.

Development version `1.5.0.dev0` may build and pass candidate acceptance but must never be formally published. PyPI uses only manual Trusted Publishing from the exact successful main CI artifacts, with protected `pypi` environment approval and minimal OIDC permissions. No tag automatically uploads. The PyPI project/pending publisher and GitHub environment must be configured by the authorized maintainer before a separately authorized formal release. A PyPI 404 does not reserve the name. Public-index install verification occurs only after publication.
