# 更新 mihomo-userctl

[English](../en/update.md) · [文档索引](README.md) · [更新 Prompt](agent-update-prompt.md)

此功能只更新 **mihomo-userctl 控制器与 Bash 集成**。不会升级 Mihomo 核心、改变订阅、
provider、节点或路由，不会启动/启用服务、配置 linger、使用 sudo、修改系统代理或停止进程。
保留服务原有的 active/enabled 状态，包括原本已 enabled 的服务。

更新器要求 Linux、Bash 5+、Python 3.8+、原控制器依赖，以及可用的 systemd 用户管理器。
[v0.2.0](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v0.2.0) 是首个支持此流程的
正式版本；旧版安装需要先完成下文的一次性迁移。目标必须是实际已发布的
正式 `vX.Y.Z` 标签，且带有声明更新协议 1 的 `release-manifest.json`；旧版发布不兼容。
查询到 latest 不代表目标兼容，请先预演。

## 命令与退出码

Git 克隆安装和 ZIP 安装都使用同一入口。安装后不再依赖原源码目录、ZIP 文件或 `.git`。

```bash
mihomoctl update --check
# 替换为已选定且实际发布的正式标签，不要填 main 或 latest。
UPDATE_TAG='vX.Y.Z'
mihomoctl update --version "$UPDATE_TAG" --dry-run
mihomoctl update --version "$UPDATE_TAG"
rc=$?
printf 'update_rc=%s\n' "$rc"
```

`--check` 读取安装元数据并查询官方最新正式发布，不修改活动安装；发现更新仍是查询成功。
`--dry-run` 在私有临时目录下载、安全解压、执行目标要求的验证，展示标签、commit、归档身份、
影响文件、原安装路径、检查及备份/回滚计划，不替换活动文件、不改变服务状态；允许创建私有
临时目录和锁目录。实际更新必须指定标签。拒绝预发布、草稿、分支名、已安装标签被移动及降级。

| 退出码 | 含义 |
| --- | --- |
| 0 | 查询或预演成功，包括发现可用更新 |
| 1 | 下载、验证、安装或最终一致性检查失败；需分别查看文件与回滚结果 |
| 2 | 参数错误、版本不兼容、路径/元数据未知或不安全、需要审查本地改动 |
| 3 | 指定版本已安装或原本就已安装；端到端验收仍有 UNVERIFIED/DEFERRED |
| 4 | 另一个安装、更新或卸载操作持有锁 |
| 5 | 文件安装及环境保持检查成功，但 Listener 验收脚本报告 FAIL |

不能把所有非零退出码都解释为文件更新失败，也不能把 3 写成“全部通过”。遇到 5，检查具体的
Listener/认证证据；更新器不会通过重启服务或撤销正确的文件安装来掩盖网络错误。
下文的一次性迁移入口采用相同退出码。[独立验收脚本](acceptance.md)有自己的退出码定义。

## 来源与验证

只使用 GitHub 上的 `liuzq1103/mihomo-userctl` 官方项目。通过 API 解析已发布标签，逐层解析
附注标签至完整 commit，再从 `codeload.github.com` 按**该 commit**下载源码 ZIP。
不使用 `curl | bash`，不跟随可变的 main。拒绝非官方重定向、路径穿越、链接/设备文件、大小写
冲突、多根目录、加密条目、体积/数量超限、损坏 ZIP 及不完整发布。

记录 release ID、标签、commit、归档 URL 和实际计算的 SHA-256。本流程使用生成的源码归档，
不是上传的二进制发布资产；没有采用独立的官方归档摘要或签名，相关验证必须标为
**UNVERIFIED**。实际依据是 HTTPS 与 GitHub 的标签到 commit 映射；自行计算摘要不等于
验证发布者身份。首次从 Git 安装只记录本地 HEAD 与 dirty 状态，不声称验证了官方历史；
没有记录的 ZIP 历史来源保持未知。

协议 1 要求版本标记一致并执行 `installation-v1` 验证：Bash 语法、隔离安装/Shell 回归、
验收器回归、审计工具失败回归、文档链接及已配置的敏感模式扫描。使用临时 HOME 和模拟服务，
每条检查有超时；工具缺失或验证失败会停止更新。这是对受信任官方发布代码的检查，不是用来
执行恶意代码的操作系统沙箱。CI 另外运行更新器集成测试，包含失败与回滚路径。

## 路径、本地改动与保留范围

新安装记录实际 HOME、XDG_CONFIG_HOME、XDG_DATA_HOME、可执行文件及 Shell 启动文件。
支持自定义 XDG 和 `--bashrc` 路径；要求绝对路径、当前用户拥有、路径中无符号链接、目标目录
不允许组/其他用户写入；启动文件必须位于 HOME 内。后续终端未导出 XDG 变量也使用原记录。
更换 HOME 或目录布局需要审查后迁移；更新器不会猜测替代路径或扫描其他用户。

锁、事务备份、文件替换和回滚统一由安装器负责。每版代码放入 `generations/<id>`，固定启动器
每次调用只解析一次版本目录；原子切换 `current` 符号链接同时发布所有模块，包括更新器自身。
保留旧目录供运行中的调用及回滚使用，当前没有自动清理旧版本功能。

实际变更范围是项目代码、来源记录和版本指针。共享安装器会备份/替换固定启动器和启动文件中的
托管块；协议 1 拒绝其布局变化。保留 `mihomo-shell.conf`、`client.env`、端口、服务名以及
启动文件非托管内容。Mihomo 二进制、config.yaml、订阅/provider/节点/路由文件和 unit 都不属于
安装目标。最终检查比较配置字节/权限、非托管启动内容及服务状态。

路径不安全、权限不符合要求、已安装代码或托管块被修改、初装来源记录为 dirty 时，会停止自动更新。
个人设置放在配置文件中；代码定制需要单独审查和移植，不要删除哈希或伪造元数据绕过检查。

## 旧版 Git / ZIP 安装的一次性迁移

旧版可能没有 `update` 命令或来源记录。没有独立证据时，历史来源必须报告为**未知**，不能补造
历史 commit。取得并检查包含 `scripts/migrate.py` 的官方发布源码即可，原安装目录可以已删除。
Git 副本应检出选定的已发布标签、核对解析的 commit 和工作树状态；ZIP 副本应使用官方发布源码，
解压前检查路径，解压后审查迁移脚本和安装器。不要执行未经检查的下载，也不要将网络响应直接送入
Shell。迁移脚本随后会复用更新器的下载/验证流程，独立按固定 commit 获取选定的官方发布。

在已经检查的源码目录内，显式指定所有原路径：

```bash
# 仅为示例，必须换成从现有安装核实的路径。
CONFIG_HOME="$HOME/.config"
DATA_HOME="$HOME/.local/share"
STARTUP_FILE="$HOME/.bashrc"
UPDATE_TAG='vX.Y.Z'
python3 scripts/migrate.py --version "$UPDATE_TAG" \
  --config-home "$CONFIG_HOME" --data-home "$DATA_HOME" \
  --bashrc "$STARTUP_FILE" --dry-run
python3 scripts/migrate.py --version "$UPDATE_TAG" \
  --config-home "$CONFIG_HOME" --data-home "$DATA_HOME" \
  --bashrc "$STARTUP_FILE"
```

执行前审查旧托管代码的本地定制：旧安装没有可信哈希，无法自动区分这些改动；迁移会替换托管代码。
无需重新指定端口，现有配置和凭据必须通过验证。脚本复用同一安装事务并保留服务状态，记录新安装
发布的来源，不追认旧安装历史。它只接受在显式路径上的旧式平铺安装，且必须能识别旧版本。
已经采用 generations 但元数据缺失/损坏的安装，应先恢复匹配备份，不能按平铺旧安装迁移。
无法确定路径或版本时，先处理具体诊断再写入。

## 网络失败、恢复与回滚

网络/API 限流、TLS、归档或目标验证失败不会改变活动文件。稍后重试同一目标；不会自动降级、
换镜像或改追 main。同一发布重复执行时，先核对完整性及来源，再作为无操作返回，验收仍需单独完成。

每次实际安装输出原 XDG_DATA_HOME 下 `mihomo-userctl-backups/install-...` 私有备份目录，
包含 `manifest.tsv`、原托管文件、`transaction.json`、可用时的 `result.json` 和独立恢复脚本。
备份可能包含启动文件里的个人设置，保持目录私有，不要粘贴或上传整个目录。

使用**本次事务实际输出**的回滚命令，例如：

```bash
BACKUP='/从更新报告取得的绝对路径/install-...'
python3 "$BACKUP/restore.py" rollback "$BACKUP"
```

无需原源码目录、可运行的 mihomoctl 或可用的 systemd 管理器。恢复脚本取得同一操作锁，恢复原
托管文件和上一版本指针，不操作核心和服务。重复已完成的回滚不再替换文件；旧备份不能覆盖后续
更新。更新后又编辑了被备份文件时，回滚会拒绝覆盖，请先在本机比较并合并新个人改动。
不要只恢复某个控制器或模块而混用不同代代码。

普通安装失败自动触发事务回滚。SIGKILL/掉电可能留下 `pending-install.json`，后续变更会被阻止，
需用其中记录的备份恢复。正常 generations 更新时，固定启动器只看到完整旧版或完整新版；从旧式
平铺布局迁移时若中途被终止，可能要先使用备份助手才能继续运行 mihomoctl。回滚本身也可能因磁盘/
权限错误失败，此时报告 **UNVERIFIED**，检查私有备份并修复文件系统，不能声称已恢复。

## 验收与重新连接

| 项目 | 所需证据与通常状态 |
| --- | --- |
| 文件已安装 | 实际安装版本、commit、文件哈希及最终检查通过后才是 PASS |
| 环境已保留 | 配置及 active/enabled 的前后比较 |
| Listener / 认证 | 只对原本 active 的服务复用验收探测；停止状态为 UNVERIFIED |
| 实际目标走代理节点 | 需要目标规则及选中节点/出口证据，否则 UNVERIFIED；到达本地 Listener 不足以证明 |
| 新 Shell 已加载 | 用户新开终端检查版本、函数和 hook 前为 DEFERRED |
| 长期运行 Codex / VS Code | 用户重连自己的客户端、取得新进程并验证前为 DEFERRED |

不会为了验收启动已停止的服务，也不会停止服务测试生命周期。更新或回滚后重新打开终端；
当前 Shell 已加载的函数仍是旧代码。自行选择合适时机重连自己的远端客户端，更新器不终止进程。
实际目标路由和客户端验收参见[证据指南](acceptance.md)，禁止输出凭据、完整代理 URL 或订阅 URL。
