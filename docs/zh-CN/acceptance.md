# 安装验收与证据要求

验收分为 Listener 基线和端到端使用验证。安装成功、`doctor` 成功、目标网站
可访问，是不同的结论；每项只报告实际取得的证据。

`mihomoctl ready` 通过认证 Listener 检查固定 readiness URL；
`mihomoctl diagnose url` 增加用户指定目标，并分开报告 direct、Listener、认证和
目标请求。两者都不识别所选节点。`mihomoctl rules check` 是结构契约检查，不是
完整路由验收。

## 1. 四种结果

| 状态 | 含义 |
| --- | --- |
| PASS（通过） | 已执行检查，观察值满足该项断言 |
| FAIL（失败） | 已观察到不符合预期的行为或请求失败 |
| UNVERIFIED（未验证） | 未执行、工具失败、输出缺失，或证据不足以判断 |
| DEFERRED（延后） | 用户明确决定稍后执行；必须记录原因和后续动作 |

不需要的可选功能应在报告的范围栏写“未选择”，不算通过。已选择的功能若仍有
FAIL、UNVERIFIED 或 DEFERRED，不得写“全部验收通过”。

## 2. 固定的 Listener 验收脚本

在当前用户的已审核检出目录中运行；需要 Bash、Python 3.8+（安装与更新也需要）、
curl、systemctl、ss 和已有的权限 600 配置/凭据。使用包含此脚本的固定版本或
已审核 commit；旧版缺少脚本时不得用临时拼接命令冒充同一版本的验收。

先手动启动自己的服务。下面的 URL 是公开、无凭据的测试目标：

```bash
acceptance_rc=0
bash scripts/acceptance.sh \
  --url https://www.gstatic.com/generate_204 --expect-status 204 \
  || acceptance_rc=$?
printf 'acceptance_rc=%s\n' "$acceptance_rc"
```

省略 `--url` 时使用 `MIHOMO_READY_URL`；省略 `--expect-status` 时接受真实
2xx 响应并打印实际状态码，不会把成功硬写成“204”。URL 不允许用户信息、查询
字符串或 fragment；不要传入订阅、签名下载或令牌 URL。每个探测默认 10 秒，
可用 `--timeout 1–60` 调整。

脚本只读取当前用户配置、查询服务/监听并发起有限网络探测，不写配置，不启动、
停止或 enable 服务，不 source `.bashrc`，不下载大文件。凭据由现有白名单
解析器校验后通过子进程环境传递，不进入命令参数；curl 忽略 curlrc、清除继承的
代理绕过变量、不跟随跳转，仅对目标发 HEAD 请求（不下载响应正文）。所选目标
须支持 HEAD，预期状态也按 HEAD 确认；输出中不含原始错误、正文或认证 URL。

自动检查包括：

- 服务为 active，启动设置为 disabled；
- 所选 TCP 端口的监听全部为 `127.0.0.1`；此项不证明进程归属或其他端口状态；
- 认证 HTTP CONNECT 和 SOCKS5H 请求的真实状态码、curl 退出码和 Listener 对端；
- 无认证 HTTP CONNECT 必须观察到来自 Listener 的 `407`；超时、502、TLS
  失败均不能当作认证拒绝；
- 无认证 SOCKS5 只提供方法 `00`，必须收到 `05 ff`（无可接受的认证方法）。
  接受 `00` 判为失败；断线或超时判为未验证。

输出为 `状态<TAB>检查项<TAB>证据`。退出码：1 表示存在 FAIL；2 表示仍有
未验证/延后项或验收器无法运行；0 仅表示报告中的项目全部通过。由于脚本保留
端到端人工证据项，即使 Listener 基线全通过，正常情况下仍会退出 2。
这不等于安装失败，也不得把它抹掉后声称完整验收通过。

只有用户明确延后 VS Code 验收时才加 `--defer-vscode`。最终报告应保留脚本
原始结果，另附后续独立验证的证据，不要手工把脚本输出改成 PASS。

## 3. 端到端证据

| 项目 | 所需证据与边界 |
| --- | --- |
| Proxy 出站 | 对已确认命中 Proxy 的公开目标发请求，关联时间、目标、规则及实际代理出站；在本地检查节点信息，报告只写是否选中代理节点 |
| 已安装 Shell | 全新一次性普通 Shell 为 direct；proxy_on/off 和 with_proxy 隔离成立；loader 位于非交互 guard 前；就绪 hook 可达 |
| 失败路径 | 经批准且无工作中断风险时，验证停止、端口释放、hook 失败退出且不自动启动、重启恢复；否则跑隔离测试并明确“实机未验证” |
| 下载 | 分别检查实际 axel、S3 客户端和大文件任务的代理设置与对应 PID socket；小文件成功不能替代大文件实测，日志零增量只能作为辅助 |
| VS Code/远程客户端 | 对重连后的新 PID 检查归属、变量存在性、Listener socket 和目标路由；停止旧进程不是新进程成功的证据 |
| 日志与源码 | 在本地按明确范围检查敏感值，仅分享计数；记录检查范围与工具退出码，不保证“绝无泄漏” |
| 基线变化 | 对照安装前后当前用户范围内的配置、监听及服务状态；单独的端口集合不能证明所有其他用户均未受影响 |

虚构示例中的 `example.com` 与 `example.net` 可以使用不同策略。readiness/认证
请求通过只证明 Listener 上实际测量的请求可用，不证明代理节点或应用端到端可用。
provider/url-test 的健康检查也不能代替应用请求的规则命中证据。

若服务已在使用，禁止为验收随意停服。运行以下隔离回归检查，并在报告中区分
仓库测试与目标机器实测：

```bash
bash tests/test.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/audit-test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
git diff --check
```

每条命令都必须保留退出码。使用日志管道时启用 pipefail 并立即记录
`PIPESTATUS`，不能以 `tail`、`tee` 或成功提示的退出码替代被检查程序。
仓库 secret-scan 只检测配置的有限模式和误放的 client.env，不扫描实机全部日志、
凭据文件或历史提交；它不会打印命中值，工具失败也不会返回“clean”。

## 4. 可复核报告

至少记录：源码 tag/commit（批准使用归档时记录归档 SHA256 及偏差）、Mihomo
固定版本和完整资产名、官方预期摘要与本地实际摘要、配置端口、active/enabled、
准确修改路径、安装前状态和备份清单。版本字符串不能替代来源校验。

每项结果使用四种状态之一，并列出命令/工具、退出码、脱敏观察值、范围与时间。
未执行项目不能推断为通过，缺少原始输出时写未验证；延后项写明原因与下一步。
附加测试证据与原始脚本结果应分别保留。总体结论应为“安装完成，验收尚有待办”
或准确的失败状态，直到选定范围内的必需项目全部取得证据。

## 5. 回滚顺序

`uninstall.sh` 只卸载控制层与 loader，保留 Mihomo 二进制、service、配置、
凭据和缓存；它不是完整卸载，也不保证恢复安装前版本。

修改前的备份与 `after-test` 等安装后快照必须分开列出。原文件不存在时，
应在清单中记录 absent；恢复“原先不存在”不能通过复制安装后快照完成。
控制层事务备份不覆盖另行安装的核心、unit 或 VS Code 设置。

回滚完整环境前先停止自己的用户服务。恢复旧二进制及配置后，用保留下来的
二进制做 `mihomo -t`，恢复 unit 后执行 `systemctl --user daemon-reload`。
若是撤销全新安装，应按获批清单移除新增 unit/配置，daemon-reload 后再移除
二进制；不能删掉二进制之后又调用它做检查。恢复 `.bashrc` 时保留原权限，
并避免覆盖安装后的其他用户修改。VS Code 从安装前备份恢复或只撤销本次键，
经批准重载后检查新进程。

仅更新控制层时保留原 active/enabled 状态，不为验收启停服务；使用
[更新与回滚](update.md)中的 generations 恢复助手。核心/完整环境回滚属于不同范围。
