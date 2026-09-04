# 架构与数据流

## 组件职责

```text
.bashrc managed loader
  └─ 校验所有者和权限后 source shell.bash
       ├─ proxy_on / proxy_off / proxy_status / with_proxy
       └─ common.bash
            ├─ 白名单解析 mihomo-shell.conf
            ├─ 白名单解析 client.env
            ├─ 权限与 endpoint 校验
            └─ service/listener/readiness 公共检查

mihomoctl
  └─ common.bash
       ├─ systemctl --user mihomo
       ├─ ss 检查 127.0.0.1:<port>
       ├─ curl 认证 readiness
       └─ journalctl --user
```

`.bashrc` 只负责建立可信边界，不包含服务管理实现。即使 Shell 集成损坏，用户
仍可直接运行 `~/.local/bin/mihomoctl doctor`，从而避免“排错工具本身依赖损坏
的 `.bashrc`”这一循环依赖。

## 两套独立状态

服务状态：

```text
down ── mihomoctl start ──> up
 up  ── mihomoctl stop  ──> down
```

当前 Shell 状态：

```text
direct ── proxy_on  ──> proxied
proxied ─ proxy_off ──> direct
```

`mihomoctl exec -- ...` 复用 `proxy_on` 的同一个校验与导出函数，随后用目标命令替换
控制器进程；`mihomoctl direct -- ...` 在替换前清除同一组八变量。两者都无法修改父进程环境。

已安装的 `diagnostics.py` 负责稳定 JSON 和同 UID `/proc` 检查，只关联环境变量数量与
socket inode，不返回环境值、命令行或远端地址。`acceptance.py` 同时提供完整验收和较窄的
`test-url` profile，使 HTTP/SOCKS 探针只有一套实现。

两者不会隐式联动，唯一例外是兼容包装器 `mihomo_stop` 会先 `proxy_off`，防止
当前 Shell 留下指向已停止端口的无效环境变量。

## 一条普通下载的路径

```text
axel → 服务器网络接口 → 目标站点
```

只要 Shell 为 direct，Mihomo 即使正在监听也不会自动截获流量，因为本项目不
使用 TUN、透明代理或路由修改。

## 一条 with_proxy 命令的路径

```text
父 Shell（direct）
  └─ 子 Shell：加载经过校验的本地凭据
       └─ command → 127.0.0.1:<port> → Mihomo → 规则决定 DIRECT 或代理节点
  └─ 子 Shell退出，父 Shell仍为 direct
```

Mihomo 内部的域名规则、策略组、节点选择和最终 fallback 不属于
`mihomo-userctl`；本项目只决定程序是否进入 Mihomo。任何数据集或科研站点的
专属规则都应留在用户自己的 Mihomo 配置中，而不是进入公共控制层。

## 三种 Codex 启动路径

```text
终端：with_proxy codex → 继承八个代理变量 → Mihomo
Codex Remote：远程启动器提供 CODEX_REMOTE_PAYLOAD → .bashrc hook → Mihomo
VS Code Remote：Machine http.proxy → Extension Host 启动 Codex app-server → Mihomo
```

三条路径彼此独立。Ubuntu 的 `.bashrc` 常在非交互 Shell 中提前 `return`，所以
managed loader 必须位于该 guard 之前。VS Code Remote 不执行 Shell 函数，也
不应假定它会提供 `CODEX_REMOTE_PAYLOAD`；需要单独配置 Machine `http.proxy`。
当前同版扩展的实机行为是把 `HTTP_PROXY`、`HTTPS_PROXY` 传给 Codex 子进程，
而不是导出终端使用的全部八个变量。

环境变量只在创建进程时继承。旧 Codex App Server 或 Extension Host 即使在
配置修复后仍可能保持 direct，必须重启当前用户自己的客户端连接，再以新进程
的环境、到 Listener 的 socket 和 Mihomo 日志完成验收。

## 文件信任模型

- `.bashrc` loader 在 source 前检查 `shell.bash` 和父目录；
- `shell.bash` 在 source 前再次检查 `common.bash`；
- 控制器独立检查 `common.bash`；
- 配置和凭据只作为文本解析；
- 未知字段、重复字段、非法引号、非法 URL 或权限均导致 fail closed。

## 安装版本

固定启动器每次调用只解析一次 `current`，加载完整的 `generations/<id>` 版本目录。
安装器统一负责操作锁、事务备份、原子发布及回滚；元数据记录原 XDG/启动路径和文件哈希，
更新器调用同一安装器。详见[更新机制](update.md)。
