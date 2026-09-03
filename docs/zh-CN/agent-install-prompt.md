# 可直接复制给 Coding Agent 的安装 Prompt

请把这份 Prompt 交给能够读取文件、执行终端命令、在需要时通过 SSH 连接目标
Linux 账户，并能暂停等待你回复的 Coding Agent。只有普通聊天能力的模型不能
代替你执行安装，只能解释人工步骤。

把下面文本块复制到一个新任务中即可。不要在 Prompt 或聊天中追加订阅 URL、
密码、令牌、私钥或其他凭据。

```text
请为我当前的、无管理员权限的 Linux 账户安装 Mihomo 和 mihomo-userctl。
最终状态必须是：systemd 用户服务只能手动启动且保持 disabled；带认证的 Mixed
Listener 只绑定到 127.0.0.1 和用户明确选择的唯一端口；新 Shell 默认直连；
只有 proxy_on、with_proxy 或本机已验证的 Codex Remote 兼容钩子
CODEX_REMOTE_PAYLOAD 显式启用代理。只操作我的账户，不影响其他用户。

必须严格遵守下面的协议。

阶段一：能力检查、只读审计和计划

1. 在做其他事情前，先确认你具备以下能力：
   - 读取和检查文件，并且不会在输出中暴露敏感信息；
   - 在目标 Linux 账户中执行终端命令；
   - 目标在远程时能够使用 SSH；
   - 能在当前对话中暂停、提问并等待我的回复。
   如果缺少任何必需能力，不得修改任何内容，也不得声称安装成功。请停止执行，
   只给出缺失部分的准确人工操作说明。
2. 只进行只读审计：确认当前用户、HOME、CPU 架构、Linux 发行版、libc 兼容性、
   Bash 版本、systemd 用户管理器、所需命令、当前代理变量、已有 Mihomo 文件和
   用户服务、Shell 启动文件、当前监听、正在运行的下载及相关 SSH 会话、候选
   项目检出目录，以及可能修改的文件。本阶段不得使用 sudo、root、其他账户、
   系统级服务、linger、cron、TUN、controller 或系统代理；不得停止进程、变更
   端口、启动服务或写文件。已有 127.0.0.1:7890 和所有归属不明的监听都属于
   范围外，除非我另行明确授权；其他用户始终完全不在范围内。
   同时只读检查 `.bashrc` 中 managed loader 与常见非交互
   `case $- ... return` guard 的相对顺序，以及当前用户自己的 Codex App Server、
   VS Code Extension Host 和扩展 Codex 子进程是否早于安装启动、是否继承代理
   变量；只报告变量是否存在和计数，不得输出值。
3. 通过普通对话向我逐项确认非敏感选项，每次最多提出三个简短问题。确认项目
   检出路径、Shell 启动文件、readiness URL、服务名、订阅接入方式、现有配置
   的保留/合并方案、策略选择和最终的每用户端口。项目没有默认端口；同一服务
   器上的用户必须选择不同端口。另请明确询问我是否需要 VS Code Remote 中的
   Codex 扩展使用代理；这是可选、独立且可能影响其他远程扩展的 Machine 设置，
   未经明确选择不得配置。不得要求我把敏感信息粘贴到聊天。
4. 敏感信息必须留在目标机器本地。Listener 凭据应在本地生成且不得打印；订阅
   URL 或已有凭据应由我直接写入属于当前用户、权限为 600 的文件。你只能接收
   文件路径，并在不回显值的前提下检查所有者、权限和必需结构；不得让值进入
   命令、工具输出、日志、diff 或最终报告。如果现有工具无法保证这条边界，请
   暂停，并给出由我在本地手动写入的步骤。
5. 修改前输出完整实施计划，列出准确文件、命令、备份、验证步骤、失败停止条件
   和回滚方法。先消除歧义，再等待我对该计划的明确批准。沉默、此前要求审计，
   或者对其他范围的批准，都不构成修改授权。

阶段二：取得明确批准后实施

6. 只有我明确批准阶段一计划后才能继续，并且不得超出获批范围。每组写入前先
   创建带时间戳、仅当前用户可访问的备份，并验证备份可恢复。不得以其他用户
   身份认证，也不得停止未知监听、ssh/sshd 进程、正在运行的下载或无关会话。
7. 调用任何项目脚本之前，必须先取得 mihomo-userctl 仓库：克隆或检查我确认的
   项目检出目录，验证 origin 是 https://github.com/liuzq1103/mihomo-userctl，
   检出固定的已发布标签，并阅读 README、setup、安全文档和安装器帮助。不得把
   网络下载内容直接通过管道交给 Shell 执行。
8. 只有在仓库检出并验证完成后，才能运行 ./install.sh --suggest-port。它输出的
   只是候选端口，不是预留结果。请与当前所有可见监听对照，让我确认最终端口，
   并在绑定前立即复查。不得检查、停止或占用归属不明的监听。
9. 从 docs/zh-CN/setup.md 的 Mihomo 安装步骤开始执行。Mihomo 只能从官方 Release
   下载；固定版本和资产；安装前核对官方摘要；每个候选配置都先做语法验证，
   再原子替换。Listener 必须带认证、只绑定 loopback、使用已确认端口。TUN 和
   external controller 保持关闭。除非我另外审核并批准策略，否则最后一条保持
   MATCH,DIRECT。已有策略规则、订阅、provider 和节点数据都属于用户所有；未经
   脱敏 diff 和我的单独明确批准，不得替换。
10. 获批计划需要时，创建仅当前用户可访问的 provider/cache 路径和 systemd
    用户 unit。非敏感 Shell 设置写入 mihomo-shell.conf；带认证的本地端点 URL
    写入权限 600 的 client.env。订阅 URL、凭据、provider 内容和私有节点数据
    不得进入 Git、聊天、命令参数、日志、截图、diff 或报告。
11. 在已验证的检出目录中，先运行文档规定的 Bash 语法检查、可用时的
    ShellCheck、完整测试套件、文档/链接测试、敏感信息扫描和空白检查；任一失败
    都必须停止。测试清单同时包含 python3 -m unittest discover -s tests
    -p 'test_*.py' -v 和 bash tests/audit-test.sh。随后执行确定性控制层流程：先运行 ./install.sh --dry-run
    --port PORT，再运行 ./install.sh --port PORT --bashrc PATH。只能替换阶段一
    确认过的值。不得 enable 服务，不得修改当前用户获批路径以外的文件。
12. 验证安装后的 Shell 集成，但不要自行定义或持久导出 CODEX_REMOTE_PAYLOAD。
    每次普通 Shell 加载必须先执行 proxy_off。远程启动器提供非空
    CODEX_REMOTE_PAYLOAD 时，模块必须自动执行等价于 `proxy_on || exit 1` 的
    逻辑：服务就绪时使用带认证的用户 Listener；不可用时 fail closed；绝不自动
    启动 Mihomo。文档必须说明该变量只是本机已验证的兼容钩子，不是公开、稳定
    的 API；远程客户端升级后要重新验收。managed loader 必须位于 Ubuntu 常见
    的非交互 `.bashrc` 提前 return guard 之前，并用非敏感的一次性子进程测试
    确认 hook 可达、普通父 Shell 仍为 direct。环境变量只在进程启动时继承；
    如发现安装前启动的当前用户 Codex App Server，先报告 PID、UID、父子关系和
    脱敏环境计数，获得我明确批准后再正常重连或精确停止。不得按名称批量杀进程，
    也不得处理其他用户。
13. 如果我在阶段一明确选择 VS Code Remote 集成，先阅读
    docs/zh-CN/vscode-remote.md。备份并结构化合并服务器侧
    ~/.vscode-server/data/Machine/settings.json：从 client.env 在本地读取
    MIHOMO_HTTPS_PROXY，绝不回显其值，将其设置为 http.proxy，同时保持
    http.proxyStrictSSL 为 true，并把活动文件和含凭据备份权限设为 600。
    不得假设 VS Code 扩展会提供 CODEX_REMOTE_PAYLOAD，不得改用全局 profile
    或 server-env-setup。只在我批准后重载当前用户自己的 VS Code 连接。
14. 启动服务前先验证配置语法。测试启动只能使用 systemctl --user。确认
    systemctl --user is-enabled mihomo 始终返回 disabled。不得启用 linger，
    也不得创建任何自动启动机制。
15. 在不暴露敏感信息的前提下完成最终验收：认证 HTTP 和 SOCKS5H 成功；未认证
    请求失败；Listener 只监听所选端口的 127.0.0.1；新 Shell 默认直连；
    proxy_on 和 proxy_off 正常；with_proxy 只影响子 Shell；CODEX_REMOTE_PAYLOAD
    路径在服务就绪时进入代理、不可用时明确失败而不是悄悄直连，并且不会自动
    启动服务；普通 axel、S3 和大文件下载保持直连；停止服务后端口释放；日志和
    项目检出中没有敏感值；其他用户与无关监听没有发生变化。如果停止正在使用
    的服务会中断当前工作，失败路径必须使用项目的隔离测试环境验证。如果选择了
    VS Code Remote，还要确认新扩展 Codex 子进程包含 HTTP_PROXY 和 HTTPS_PROXY
    （只报告 `2/2`，不输出值）、连接用户 Listener，目标域名出现在 Mihomo 脱敏
    日志；Extension Host 本身可以为 `0/2`。
16. 如果写入或验收失败，立即停止；在安全且可验证时从备份恢复受影响文件，
    并报告剩余状态。绝不杀死未知进程、扩大权限、使用 sudo 或悄悄弱化检查。
17. 最后提供脱敏报告：版本和已验证摘要、所选端口、修改文件、备份位置、服务
    active/enabled 状态、验收结果、跳过或失败的检查，以及准确回滚步骤。报告中
    不得包含任何敏感值。若选择 VS Code Remote，还要列出 Machine 设置的权限、
    新进程的变量存在性和 socket/log 验收结果，不得列出代理 URL。

18. 严格遵守 docs/zh-CN/acceptance.md 的证据与报告规则：
    - 先运行 bash scripts/acceptance.sh，使用已确认的公开 HTTPS 目标，需要时
      明确 --expect-status；保存脱敏原始输出和实际退出码。脚本退出 2 表示尚有
      UNVERIFIED/DEFERRED，不得当作安装失败，也不得忽略后声称全部通过。
      缺少脚本或 Python 等依赖时写 UNVERIFIED，不得用临时命令冒充已运行脚本。
    - 每项只能写 PASS、FAIL、UNVERIFIED、DEFERRED，并列出命令、退出码、
      脱敏观察值、范围和时间。DEFERRED 必须对应我的明确决定及后续动作；
      未选择的可选项单列范围，不能算 PASS。只要选定范围的必需项还有未验证、
      延后或失败，总结就必须明确“安装完成但验收未完成”或实际失败情况。
    - 必须读取实际 HTTP 状态码。认证请求成功不等于状态必为 204；无认证请求
      的超时、TLS/网络错误不等于认证拒绝。区分 Listener readiness 与 Proxy
      出站证据；gstatic.com 在默认示例中走 MATCH,DIRECT，不能据此宣称节点
      或 OpenAI 已可用。不得根据小文件成功、环境变量计数或日志零增量，推断
      S3/大文件或目标应用已经实测通过。
    - 只写配置或停止旧进程不算 VS Code/远程客户端验收完成；必须验证重连后
      的新 PID、变量存在性、socket 和路由。停服有中断风险时运行隔离测试，
      同时把真实环境对应项目记为 UNVERIFIED，不能把模拟结果写成实机结果。
    - 每条检查保存真实退出码；管道启用 pipefail 并立即保存 PIPESTATUS，
      不得用 tail、tee 或 echo 的成功掩盖原命令失败。缺少原始输出时只报告
      “记录声称通过，未独立验证”。敏感信息扫描仅报告范围和计数，不能由
      有限模式无命中推断“绝无泄漏”；不得打印命中的敏感值。
    - 记录源码 tag 与 commit；明确批准使用归档等来源偏差时，记录归档
      SHA256、可取得的 commit 和缺失的来源证据。固定 Mihomo 完整资产名、
      官方预期摘要与实际摘要；版本字符串或 PROVENANCE 文件本身不构成校验。
    - 分清安装前备份、安装后快照和原先不存在的文件；先停服，再恢复并验证，
      删除新二进制只能在所有需要它的验证之后。uninstall.sh 保留核心、unit、
      配置及凭据，不得称为完整卸载。回滚须按准确清单保留原文件权限及后续
      无关修改；不得声称用 after-test 快照恢复了安装前状态。
```

这份 Prompt 是编排协议，不替代仓库中确定性的安装器和测试。请先审核 Agent
给出的阶段一计划，再决定是否批准实施。
