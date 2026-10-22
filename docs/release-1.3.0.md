# 1.3.0 release notes / 发布说明

Textual is now installed privately, in your own generation directory, exactly as
PyYAML already was. `bash install.sh --user --python PYTHON --wheelhouse DIR
--extras tui` stages `textual==8.2.8` and its dependencies into the read-only
generation `lib`. No sudo, no system pip, no third-party index. `mihomoctl
update` accepts the same `--extras` / `--no-extras` pair.

Textual 现在随用户私有 generation 一并安装，与 PyYAML 相同。`--extras tui`
把 `textual==8.2.8` 及其依赖解包进只读的 generation `lib`，无需 sudo、无需系统
pip、不经过第三方索引。`mihomoctl update` 同样支持 `--extras` / `--no-extras`。

Delay results are now specific. `GET /proxies/<name>/delay` returning 404, 503
or 504 all collapsed into one opaque `controller-request-failed`, which hid the
cause: 404 means the name is not in the core proxy table at all. They are now
`node-not-in-core`, `node-unreachable` and `delay-timeout`. `unknown-node` echoes
the exact spelling you asked for. Health reporting lists group members that are
missing from the core table.

测速失败原因不再被合并成一个无信息的错误码：404 表示该节点名根本不在核心代理表中，
与「引用对象缺失」同源，通常意味着订阅未加载或分组仍写着旧版节点名。现在分别报告
`node-not-in-core`、`node-unreachable`、`delay-timeout`，`unknown-node` 会回显你
实际请求的完整名称，健康报告中也会列出核心表里缺失的分组成员。

A bare `mihomoctl` and `mihomoctl --help` now print a grouped command guide with
a one-line description per command; the bare invocation still exits 2. The curses
key legend is laid out by display cell and wrapped to the terminal width instead
of being clipped, and the pane header is bilingual.

裸跑 `mihomoctl` 与 `mihomoctl --help` 现在输出分组命令速查表（裸跑退出码仍为 2）。
curses 键位行按显示宽度排版并随终端折行，不再被右侧截断，面板标题中英双语。

**v1.0.0–v1.2.0 用户必须继续使用核验后的 1.3.0 安装器升级。** 旧二进制无法自行
获得新命令，也读不懂新的私有依赖暂存记录。

**Existing v1.0.0–v1.2.0 users must use the verified 1.3.0 installer.** Old
binaries cannot acquire these commands and cannot read the new private
dependency staging record.

Upgrade without extras preserves the extras already recorded. An inherited extra
that a new wheelhouse cannot resolve is carried forward from the previous
generation file by file, re-hashed against its recorded digests; anything that
cannot be attributed is dropped loudly rather than silently disappearing.
Unknown extra names fail closed.

未指定 extras 的升级会沿用已记录的 extras。若新 wheelhouse 无法解析某个沿用的
extra，会按文件从前一个 generation 结转并重新核对摘要；无法归属的部分会明确
报告 `extras-dropped` 而不是静默消失。未知的 extra 名直接失败，不静默忽略。

`docs/{en,zh-CN}/console.md` expand from a five-line stub into a real guide:
which front end has a speed test, how to install Textual privately, what each
delay outcome means, the full key map and the probe syntax.

本地更新语义、安装门禁、私有备份与自包含回滚不变。配置、订阅、凭据、既有缓存与
Mihomo 核心都会保留；不重启进程，不引入 cron、shell 启动文件、自动提权、全局
代理或隐式安装核心。摘要、receipt 与门禁记录是一致性证据，不是发布者签名。