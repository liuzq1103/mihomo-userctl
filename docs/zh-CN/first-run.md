# 安装后第一次使用 Codex

[English](../en/first-run.md) · [安装](setup.md) · [故障排查](troubleshooting.md)

安装完成不等于 Codex 已经连通。先完成个人订阅/配置，确认 Codex 已安装；登录由你本人完成。
本页的 `mihomoctl codex` 和 `mihomoctl diagnose codex` 是 v0.5.0 新增入口。
已发布的 v0.4.0 使用 `with_proxy codex`（Bash 已加载时）或 `mihomoctl exec -- codex`，
进程检查使用 `mihomoctl diagnose name codex`；升级前不要假定新命令已存在。

## 按你的启动方式操作

| 你如何使用 Codex | 正确入口 |
| --- | --- |
| 普通 SSH/Bash 终端手动输入命令 | `mihomoctl codex`，会检查 HTTP 代理就绪并提醒旧进程风险 |
| 已验证自动 hook 生效的 Codex Remote | 正常连接，不需要额外包装；变更代理后重新连接并验证 |
| VS Code Remote 扩展 | 按 [VS Code 集成](vscode-remote.md)配置，不能用终端成功代替扩展验收 |
| 脚本或其他工具 | `mihomoctl exec -- COMMAND`；Bash 中也可使用 `with_proxy COMMAND` |

`.bashrc` 中的 loader 提供函数并加载条件 hook。普通 Shell 加载时先清理代理变量；
仅远程启动器提供非空 `CODEX_REMOTE_PAYLOAD` 时自动启用。因此普通终端直接输入 `codex`
没有自动代理保证。不要把该变量永久写入启动文件，也不要添加全局代理来修复单个应用。
本项目不替换 `codex` 命令、不添加同名 alias，保留直连与其他客户端原有行为。

## 普通终端的首次检查

打开一个新终端。若 `mihomoctl` 不在 PATH 中，用 `~/.local/bin/mihomoctl` 执行，
再按安装时的 PATH 设置修复。非 Bash Shell 也可使用这个可执行入口，无须 `source .bashrc`。

```bash
mihomoctl doctor --offline
mihomoctl start
mihomoctl codex
```

先确认订阅/配置已完成再启动服务；服务已经运行时可以直接使用启动入口。
服务默认 disabled，机器重启后要按需手动启动。`mihomoctl codex` 不自动启动服务。
向 Codex 传递参数时用分隔符，例如 `mihomoctl codex -- resume`；原参数和退出码会保留。
该入口使用 PATH 中的 Codex 可执行文件，不执行 Shell alias/function，也不替你安装或登录。

启动入口的就绪检查会通过代理请求配置的 READY URL，然后才启动 Codex。
若检查失败，会阻止这次启动并提示检查配置；成功也只证明这次 HTTP 请求可用。
登录完成且你同意发出模型请求后，在同一个实际使用入口发送一句最小测试消息，确认收到完整回复。
API 用户的模型请求可能计费；诊断命令不会自动发起这类测试。

## WebSocket 报错先判断是哪一段

| 现象 | 下一步 |
| --- | --- |
| `command not found` | 确认所选工具已安装，重开终端并检查 PATH，不是网络故障 |
| `doctor`/`ready` 失败、代理认证失败 | 检查服务、个人端口、`client.env` 与 Mihomo 认证、订阅和节点 |
| HTTP 检查通过，但 WebSocket 握手失败或流中断 | 检查实际出站进程、对应目标的路由/节点、TLS/证书、网络中间设备；不能据此认定代理已完成或未完成 |
| 本地 Unix socket、localhost 的连接失败 | 检查所属客户端与 app-server 是否正常；本地连接应绕过代理，远端节点通常无法修复本地服务 |
| 401/403 或账号/配额提示 | 结合实际出错层检查登录、权限或网关限制；不要反复清空认证文件 |
| 改完代理后仍重复旧错误 | 按下面步骤退出并重连自己的旧客户端，检查是否还有旧进程被复用 |

WebSocket 可能用于客户端到 app-server，也可能用于 app-server 的远程连接；看清错误发生的
层次，不能把所有 WebSocket 都视为模型出站。参见 [Codex 官方连接说明](https://learn.chatgpt.com/docs/app-server)。
`curl` 成功、8 个代理变量齐全、某次请求回退到其他传输，都不能单独证明目标 WebSocket 已通过。
不要套用未验证版本的“关闭 WebSocket”配置，也不要关闭 TLS 校验来掩盖错误。

## 已有进程与安全恢复

```bash
mihomoctl diagnose codex
# 如需交给 Agent 分析：
mihomoctl diagnose codex --json
```

这是无联网、只读检查：报告当前环境及本用户 Codex 候选进程的 PID、角色和代理环境分类，
不输出命令参数、订阅或代理密码。`direct` 表示未读到代理变量，不等于模型请求一定直连；
`inconsistent` 表示与当前个人代理配置不匹配。匹配也不能证明 WebSocket 成功。
无进程是未运行的正常可能状态。权限不足、进程退出/变化会保留为未验证，不视作零风险。
自定义启动器可能漏检；此命令不关联 Unix socket 对端，不识别哪一个候选服务正在被你的请求复用。
因此报告整体为 `UNVERIFIED`、退出码为 `2`，即使没有发现问题；这不是模型请求失败。

1. 保存当前工作，在自己的 Codex 客户端正常退出或断开 Remote 连接。
2. 再次运行诊断。如果候选进程仍在，不要仅凭“旧”“direct”或 PID 就停止它：它可能服务于你的其他活跃会话。
3. 若需人工清理，先确认当前 PID 的 UID、对应客户端和会话，并在停止前重新核实，防止 PID 已被复用。
   只对确认不再使用的那个进程进行正常停止；不执行全局 `pkill`/`killall`，不删除 socket、`~/.codex`、登录和会话数据。
4. 从上表对应入口重新连接；确认实际服务也继承了正确环境，再做一次已授权的最小请求。

重启 Mihomo、重开一个终端或再次 `source .bashrc` 都不会修改旧 app-server 的环境。
新启动入口只提醒风险，不强停进程，也不承诺自动修复旧服务。没有关联证据时，让 Agent 按
[详细排障](troubleshooting.md)继续只读检查，避免盲目重装。

## 安装交付应告诉你什么

交付报告必须给出：实际订阅配置位置及是否已填写、服务是否启动、你的启动入口、
是否需要退出旧客户端、实际请求是否测过，以及还需你完成的登录或验证。
“控制层已安装”“HTTP 代理就绪”“Codex 收到模型回复”应分别报告，不合并成“全部可用”。
