# 可直接复制的 Codex 安装 Prompt

适合在全新服务器上让 Codex 完成审计、安装和验收。发送前替换方括号内容。
不要把订阅 URL 或密码粘贴进 Prompt；需要秘密时，只告诉 Codex 已在服务器上
创建的权限 `600` 文件路径。

```text
请为我当前登录的 Linux 用户安装用户级 Mihomo 和 mihomo-userctl。

必须达到的结果：
- 普通登录、新 Shell、axel、S3 和大型科研数据始终默认服务器直连；
- 只有 with_proxy、proxy_on 和明确批准的远程工具钩子使用 Mihomo；
- Mihomo 只有一个带认证的 Mixed Listener：127.0.0.1:[端口]；
- 只用 systemctl --user，mihomo.service 必须保持 disabled；
- 不使用 sudo、root service、linger、cron、TUN、controller、系统代理或路由修改；
- 不读取、不修改、不停止其他用户，也不以其他用户身份登录或认证；
- 不停止未知监听、ssh/sshd、下载任务和无关会话；
- 已有 127.0.0.1:7890 一律视为范围外，除非我另行明确授权；
- 订阅 URL 和代理凭据不得出现在命令参数、输出、日志、Git 或报告中。

严格按以下顺序实施：
1. 完整阅读本仓库 README.zh-CN.md 和 docs/zh-CN/setup.md。
2. 只读检查系统、CPU 架构、libc 兼容性、Bash、systemd 用户管理器、依赖、
   当前代理变量、候选端口、用户服务、下载进程和现有配置。
3. 报告精确修改范围；任何步骤需要管理员权限，或现有配置归属不明时立即停止。
4. 修改前对范围内文件创建权限收紧的备份。
5. 从 MetaCubeX 官方 Release 安装固定版本 Mihomo：下载匹配资产，核对官方
   SHA256，验证候选版本和配置后再原子安装到 ~/.local/bin。
6. 创建仅回环、必须认证的配置、私有 provider/cache、用户 systemd unit 和
   权限 600 的 client.env，全程不显示秘密。
7. 克隆或使用 mihomo-userctl，先运行测试，再执行 install.sh --dry-run
   --port [端口]，最后执行 install.sh --port [端口] --bashrc "$HOME/.bashrc"。
8. 不 enable、不设置自动启动；仅为测试手动启动服务。
9. 验证：未认证 HTTP/SOCKS 被拒绝；认证 HTTP/SOCKS5H 成功；服务 disabled；
   新 Shell direct；with_proxy 不污染父 Shell；普通 axel/S3 直连；日志和 Git
   无秘密。
10. 提供精确回滚命令和脱敏验收报告。

readiness 使用 [READY_URL]。Mihomo 末尾保持 MATCH,DIRECT。策略规则和订阅均
属于用户已有配置；未经脱敏 diff 和我的批准，不得替换。
```

这个 Prompt 只负责让 Codex 正确编排；真正写入仍由可测试的脚本完成。项目不
推荐 `curl | bash`，因为它难以在执行前审计。
