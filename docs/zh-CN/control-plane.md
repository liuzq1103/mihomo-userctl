# 节点管理与浏览器面板

[中文首页](../../README.md) · [English](../en/control-plane.md)

v0.7 控制层通过 Mihomo Controller API 显示节点、策略组当前选择与实际连接链路。
代理流量仍由 Mihomo 处理；普通 Shell 默认直连，Codex preflight 不变。

## 一次性启用

控制器命令额外需要 Python 的 **PyYAML**（`python3 -c 'import yaml'` 可检查）。
基础代理和 Codex 命令不新增依赖。若缺失，可使用发行版提供的 python3-yaml，
或在自己管理的 Python 环境安装 PyYAML 并让该环境的 python3 位于 PATH；工具不自动提权安装依赖。

确认已有 Mihomo 配置和工作目录，然后运行：

```bash
mihomoctl controller setup
# 确认可中断自己的代理连接后执行
mihomoctl restart
mihomoctl controller status
mihomoctl groups
```

默认读取 `$XDG_CONFIG_HOME/mihomo/config.yaml`（未设置时为 `~/.config/mihomo/config.yaml`），
工作目录为 `$XDG_DATA_HOME/mihomo`（默认 `~/.local/share/mihomo`）。配置必须属于当前用户且权限为 600，
工作目录权限为 700，路径不能包含符号链接。非默认部署使用：

```bash
mihomoctl controller setup --config /ABSOLUTE/config.yaml --home-dir /ABSOLUTE/mihomo
mihomoctl groups --config /ABSOLUTE/config.yaml
```

这两个路径必须与自己的 systemd 服务启动参数一致。setup 不修改服务单元、不自动重启。
它选择当前空闲的独立端口（也可传 `--port PORT`），生成随机密钥，开启选择缓存，部署内置静态面板，
只修改对应顶层配置项，保留其他节点、规则和注释；先运行 `mihomo -t`，成功后备份并原子替换配置。
端口选择是检查时的快照；启动冲突时更换空闲端口，不能结束占用者进程。

已有公开控制接口、弱密钥或附加 Unix/TLS/DoH 接口会拒绝继续，需先人工审阅。
带 YAML anchors、aliases、重复键、复杂根映射或显式文档结束符的配置不自动修改。
已有面板默认保留并停止 setup；明确提供静态包才替换面板路径。
失败时不替换配置；备份包含私密配置，保持 600，勿上传。恢复输出中给出的备份后，校验并按需重启。

## 日常命令

```bash
mihomoctl nodes
mihomoctl groups --json
mihomoctl select "Proxy" "节点名称"
mihomoctl latency "节点名称"
mihomoctl connections
mihomoctl traffic
mihomoctl tui
```

`select` 只允许手动 Selector 组中已有成员，更新后重新读取确认。URLTest、Fallback、LoadBalance 只读，
避免把自动策略悄悄固定。**远程服务器默认推荐 `mihomoctl tui`，无需 SSH 端口映射。**
全屏界面左右显示策略组和节点，`[*]` 标记当前选择。方向键浏览，Tab/左右键换栏，
Enter 进入组或确认切换，r 刷新，t 测当前节点延迟，c 查看前两条活跃链路，f 查看流量，q 退出。
每 5 秒刷新策略组；链路与流量按键采样。窄终端或屏幕阅读器可用 `mihomoctl tui --plain` 编号菜单。
切换不会强制断开已有连接；`profile.store-selected` 保存选择，能否持久化还取决于核心工作目录可写。

**策略组选择不是每个请求的实际出口。** 不同规则可指向不同组；嵌套策略组、负载均衡和已有连接还会影响路径。
`connections` 显示活跃连接的链路与规则类型，省略域名、IP、进程路径和规则内容；没有活跃连接时不能推断出口。
`traffic` 返回一次速率采样，单位 bytes/s；累计量单位 bytes。`latency` 会经所选节点请求
`https://www.gstatic.com/generate_204`，不代表真实模型请求通过。

API 输出 schema 为 `mihomo-userctl.controller/v1`；`--json` 可用于非交互查询和 setup/select/latency。
退出码：0 操作成功；1 已知请求失败或策略阻止；2 配置、依赖、检查或用法错误。
JSON 不包含密钥、订阅或原始连接元数据，但节点与组名本身可能具有隐私，请审阅后分享。

## 可选：浏览器访问

```bash
mihomoctl ui
# dashboard 是同一入口
mihomoctl dashboard
mihomoctl controller token
```

`ui` 检查控制器后显示本机 URL 和 SSH 转发模板，不自动启动浏览器。
`controller token` 是唯一显式显示密钥的入口，只允许直接输出到交互终端，不支持管道或 JSON。
在自己的私有终端运行，勿截图分享。内置面板密钥只留在内存中，不写入 URL、localStorage 或 sessionStorage。

远程服务器：将 `ui` 输出中的远端端口代入，在自己电脑运行：

```bash
ssh -N -L LOCAL_PORT:127.0.0.1:REMOTE_CONTROLLER_PORT USER@SERVER
```

浏览器打开 `http://127.0.0.1:LOCAL_PORT/ui/`，输入密钥即可看到当前策略组和切换按钮。
不要把 controller 改为 `0.0.0.0`，也不要把 SSH 转发绑定到公网接口。
浏览器面板使用同源 API，不需要开放通配 CORS，不新增后台服务。

## 使用 MetaCubeXD

从 [MetaCubeXD 官方仓库](https://github.com/MetaCubeX/metacubexd) 获取已审阅版本的**静态站点 ZIP**，
固定来源/commit 并核对可信 SHA256。不要使用桌面安装包或未构建源码包。

```bash
mihomoctl controller setup --archive /ABSOLUTE/metacubexd-static.zip --sha256 VERIFIED_SHA256
mihomoctl restart
mihomoctl ui
```

工具只接受单个 index.html 根目录的受限 ZIP，拒绝越界路径、符号链接、重复项和过大解压内容。
SHA256 校验仅证明与提供的哈希一致，不证明来源可信。不会执行下载的代码，也不会自动下载或更新面板。
第三方面板 JavaScript 会接触你输入的控制器密钥，请只部署信任的版本；其存储与操作范围遵循该面板自身设计。
在 MetaCubeXD 连接页填 SSH 转发后的 loopback 地址和密钥；内置面板被替换后不再提供其受限操作界面。

Controller 密钥与代理认证独立。命令发送密钥前检查 loopback 绑定、socket UID 和匿名认证拒绝；
这不抵御 root、同 UID 恶意进程或检查后的端口争抢。服务端 `/ui/` 静态内容不包含密钥；所有 API 仍需认证。
目前未自动管理订阅、下载核心、修改系统路由或验收真实 Codex 模型请求。

接口依据：[Mihomo API](https://wiki.metacubex.one/api/)、[外部控制和 UI 配置](https://wiki.metacubex.one/config/general/)。
