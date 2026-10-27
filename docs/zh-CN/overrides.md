# 脚本与服务器路由策略

脚本和配置必须放在本账号拥有的私有目录中（700），文件权限为 600。664 脚本会被拒绝，因为同组其他成员可以修改执行内容。还需修正属主和不安全父目录；不接受符号链接。JavaScript 是本账号信任的代码，Node VM 不是安全沙箱。system scope 仍禁止 JavaScript 覆写。

```bash
chmod 700 "$HOME/private"
chmod 600 "$HOME/private/override.js"
mihomoctl override --script "$HOME/private/override.js"
mihomoctl override --script "$HOME/private/override.js" --apply
mihomoctl restart
```

第一条 override 命令预览策略变更。`--apply` 校验并保存，不自动重启；restart 在停止旧核心前检查配置。TUI 的订阅保存按钮则在同一可恢复事务中保存并启动或重启。预览成功不代表保存、激活或远端业务请求成功。应查看实际失败阶段、配置是否提交或恢复，以及重新观测到的核心状态。

脚本只允许修改分组、规则和 rule-providers。普通模式和兼容模式均丢弃精确的 `__flclashRules` 输出键，将其视为桌面元数据；它不能授权修改监听、认证、TUN、节点或 proxy-providers。`--flclash-compat` 仅为需要内嵌节点输入的桌面脚本适配可信 provider 缓存，不扩大权限，也不下载 Node。完整应用包不包含 Node；缺少 Node 时可选择服务器 YAML。

只包含分组、规则的服务器片段应使用显式叠加模式：

```bash
mihomoctl subscription preview --source-file "$HOME/private/server-policy.yaml" --policy policy --json
mihomoctl subscription apply PREVIEW_ID --sha256 CANDIDATE_SHA256
mihomoctl restart
```

`policy` 仅替换输入中提供的 `proxy-groups`、`rules` 和 `rule-providers` 章节。省略章节、节点、proxy-providers 和运行参数均保留。引用基于合并后的完整配置校验：FlClash 服务器策略默认引用名为 `subscription` 的 provider，必要时在私有副本中调整引用，不会自动创建缺失 provider。不能把片段当作 `provider` 模式导入：完整 provider 导入有意将省略的策略章节置空。`auto` 保持原有判断，不会猜测为片段叠加。

完整策略预览执行核心检查；仅节点预览执行结构检查。TUI 只在候选字节、核心、身份及依赖资源均未变化时复用校验结果。跨 CLI 进程，或依赖不完整、发生变化时重新校验。校验只向私有隔离目录复制可信资源，不使用正式核心目录作为校验工作目录。缓存内容和原始核心日志不进入错误信息；超时不能证明现场根因就是重复下载。

成功操作删除临时事务恢复副本和预览文件，不保留历史备份或历史回滚。失败或中断时仅保留仍需用于恢复的材料；未确认的恢复不能显示为成功。另见[订阅教程](subscriptions.md)与[排障](troubleshooting.md)。
