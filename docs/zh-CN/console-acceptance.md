# 控制台验收与回滚

## 中文任务界面与完整策略导入（2026-10-09）

- Ubuntu 22.04 / Python 3.10：218 项 Python 回归，214 通过、4 个可选用例跳过；Shell 52 项、审计 6 项通过。
- 覆盖安装时控制器初始化、重复安装、已有不安全配置保护、运行服务不被重启；完整订阅策略替换、缺失引用/越界路径拒绝、候选篡改与并发修改保护，以及旧节点导入计划兼容。
- Textual 8.2.8：80×24、60×14 操作链，首次设置、分组只读行为、订阅预览/保存/重启及真实 PTY q/Ctrl+C/resize 恢复通过；无依赖编号菜单可在缺少配置时打开。
- 真实 Mihomo v1.19.32 配置校验与本机 API 验证通过，包含本地节点 Provider、嵌套分组、规则 Provider 和规则；标准输入导入在真实 PTY 的两种界面中通过。Bash 语法、ShellCheck、Python 3.8 语法、双语链接及隔离源码扫描通过。
- 使用临时 HOME 与替代 systemd 的安装夹具；未连接 MainServer，未发布或部署，未新增真实多 UID、SSH 或 systemd 验收。

## 本次本地验证记录（2026-10-08）

- Ubuntu 22.04 / Python 3.10：185 项 Python 回归，181 通过、4 跳过；52 项 Shell 测试、6 项审计回归通过。
- 4 个跳过项为 3 个 Node 用例及 1 个可选用户脚本；Windows / Python 3.9 补测 7 个策略用例通过，用户脚本仍未提供。
- Textual 8.2.8 Pilot、真实 PTY 的 q/Ctrl+C/resize 恢复、真实 Mihomo v1.19.32、离线 venv 安装/复用/坏哈希回滚通过；页面切换/退出交互另重复 3 轮通过。
- Bash 语法、ShellCheck、Python 3.8 语法、双语文档链接及源码快照 secret scan 通过。私有笔记不进入发布源码扫描。
- 未执行真实 systemd 用户管理器、两个真实 UID、远程 SSH/tmux/screen 验收。Python 3.9/3.12 可选 UI CI 已配置，远程结果以该提交的 workflow 为准。

自动回归使用虚构凭据、临时 HOME、真实 loopback HTTP/socket、真实 PTY 和 Textual Pilot。安装/更新夹具替代 systemd；这些通过不能代替真实用户服务、多 UID 和 SSH 验收。

## 自动检查

在 Linux 私有源码副本中执行：

```bash
bash tests/test.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/audit-test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
git diff --check
```

可选 UI 用锁定依赖运行 `tests/test_textual.py`。提前下载 wheelhouse 后，设置测试专用 `MIHOMO_TEST_WHEELHOUSE=/ABSOLUTE/wheelhouse`，`test_update.py` 会验证真实离线 venv、环境复用、坏哈希回滚。此变量只由测试读取，产品不存在安全门禁绕过开关。CI 分别覆盖基础模式和 Python 3.9/3.12 的可选 UI。

## 专用测试主机

由测试主机管理员提前准备两个普通账户；产品本身不提权、不创建账户。每个账户准备独立的私有配置/凭据和 systemd 用户服务，确认无需 linger 或自动 enable。

1. 两账户分别安装控制层并使用不同 mixed/controller 端口，确认监听仅绑定 127.0.0.1 且匿名 Controller 访问被拒绝。
2. A 占用 B 计划使用的端口，再由 B 执行 start/restart：必须在服务操作前 FAIL/UNVERIFIED；A 的服务/PID、B 的配置、端口和 Shell 环境不变。重复通配与 IPv6 占用场景。
3. 同 UID 的无关进程占用端口也不能通过。目标服务已经运行时，幂等 start 成功；重启后的监听须关联 MainPID/cgroup。
4. 无法读取归属、缺少 systemd 用户管理器、匿名访问被放行时，不能显示健康或发送凭据给外 UID 服务。
5. 验证跨 UID 私有文件访问被拒绝；诊断仅检查当前 UID，不读取另一账户环境或 argv。
6. 在真实 Mihomo 下切换 Selector、测速、查看 Provider/Rules/Traffic/Logs/DNS。自动组只读，旧连接保留；关闭 core 后显示 stale，再启动后恢复；写操作不自动重放。
7. 订阅先预览；更改原配置、候选、哈希、核心校验失败、磁盘/锁失败时活动字节不变。成功时检查 0600 备份及所有非 proxies 字段保持不变，服务继续运行旧配置直到显式重启。
8. SSH PTY、tmux/screen 中验证 60×14、80×24、大终端、resize、Ctrl+C、q、异常退出后终端恢复；断开 SSH 后 Mihomo 用户服务状态保持，重新进入控制台可用。
9. 在父 Shell 中记录八个代理变量，进入/退出 TUI、切换节点、模式和服务操作后逐字节比较；普通 Shell 仍直连。复核 exec/direct 子进程退出码、Codex 0/1/2 preflight 和秘密不进入 argv/导出。

只在专用主机执行占用、故障和中断测试，不对真实用户工作负载试验。

## 回滚

UI 回滚：`mihomoctl tui --engine curses` 或 `--plain`。代码回滚沿用安装输出中的私有 backup/restore 命令；不覆盖后来编辑的配置。配置备份恢复需显式选择、重新运行 `mihomo -t`、检查漂移并原子替换，重启另行执行。订阅下载或应用失败不会覆盖活动配置；raw/candidate 中含敏感内容，应按私有文件管理，不加入仓库。

回滚失败必须报告未恢复资源和私有恢复路径，不能显示成功。真实测试未执行的场景在交付记录中标注未验证。
