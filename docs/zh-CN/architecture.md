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

Mihomo 内部的 `MATCH,DIRECT`、AI 规则、SEA-AD 精确 DIRECT 等策略不属于
`mihomo-userctl`；本项目只决定程序是否进入 Mihomo。

## 文件信任模型

- `.bashrc` loader 在 source 前检查 `shell.bash` 和父目录；
- `shell.bash` 在 source 前再次检查 `common.bash`；
- 控制器独立检查 `common.bash`；
- 配置和凭据只作为文本解析；
- 未知字段、重复字段、非法引号、非法 URL 或权限均导致 fail closed。
