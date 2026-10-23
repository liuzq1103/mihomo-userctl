# 自定义规则

先 [导入订阅](subscriptions.md)。在私有 manager.yaml 中确认 `core.config` 的活动路径，编辑前预览变更并验证候选；工具不保留历史副本。当前检查契约要求名称完全等于 `Proxy` 的组；须确保该组存在且选中预期远端节点，而非 DIRECT。名称区分大小写。后续 provider 模式导入可能替换组和规则，需要重审。

创建下面三个文件，按需合并已有用户规则。已有文件不能未经合并就执行覆盖写入示例。目录权限必须为 700，文件权限 600；provider 相对路径以受管 Mihomo HomeDir 为基准，不是仓库或当前目录。

把下面 YAML 的 provider 和 rules 内容合并进活动核心配置；保留现有 listener、认证、controller、组及无关 provider。自定义 RULE-SET 都要在最后 fallback 之前。规则采用首次匹配，示例顺序为 reject、direct、proxy，具体优先级由你决定。示例域名不是完整 Codex 端点清单。
```bash
rules_dir="${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/core-home/rules"
install -d -m 700 "$rules_dir"
umask 077
cat > "$rules_dir/custom-direct.yaml" <<'YAML'
payload:
  - DOMAIN,localhost
YAML
cat > "$rules_dir/custom-proxy.yaml" <<'YAML'
payload:
  - DOMAIN,api.openai.com
YAML
cat > "$rules_dir/custom-reject.yaml" <<'YAML'
payload:
  - DOMAIN,ads.example.com
YAML
chmod 600 "$rules_dir"/custom-*.yaml
```

nodes 模式导入后若没有 Proxy 组，在活动核心配置中添加下列组。把 YOUR_IMPORTED_NODE 替换为确切的已导入节点名（查看私有订阅，或重启后运行 `mihomoctl nodes`）。已有 Proxy 组则修改成员，不要重复创建。

```yaml
proxy-groups:
  - name: Proxy
    type: select
    proxies: [YOUR_IMPORTED_NODE]
rule-providers:
  custom-direct:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-direct.yaml
  custom-proxy:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-proxy.yaml
  custom-reject:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-reject.yaml
rules:
  - RULE-SET,custom-reject,REJECT
  - RULE-SET,custom-direct,DIRECT
  - RULE-SET,custom-proxy,Proxy
  - MATCH,DIRECT
```

```bash
mihomoctl rules status --json
mihomoctl rules check --json
mihomoctl config validate
mihomoctl restart
```

检查器使用 manager.yaml 声明的核心，不从 PATH 换用另一个 mihomo。它只检查文件及执行核心配置验证，不写配置、不重启。status 和 check 均支持 JSON。契约通过不代表远端出口已验证，继续 [真实客户端验证](first-run.md)。
