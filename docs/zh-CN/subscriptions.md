# 配置订阅

完整包用户运行 `mihomoctl` 进入订阅页，在隐藏输入框粘贴 HTTPS URL，或选择本地 YAML 文件，预览后确认保存并启动。简单模式为新配置建立 `Proxy` 手动选择组与默认代理规则，保留已有自定义路由；高级完整策略导入可替换分组和规则。见 [终端指南](console.md)。

## 高级 CLI 导入

前提是已按 [初始化教程](setup.md) 建立受管运行时。订阅 YAML 或 URL 放在权限 700 的私有目录内，文件权限 600。URL 可能含凭据，不能放进参数、截图或日志；只接受 HTTPS URL。

```bash
chmod 700 "$HOME/private"
chmod 600 "$HOME/private/subscription.yaml"
mihomoctl subscription preview --source-file "$HOME/private/subscription.yaml" --policy nodes --json
```

也可使用 `--url-file "$HOME/private/subscription-url"`，或将内容通过管道交给 `subscription preview --stdin`。一次只选一种输入。`auto` 在输入包含路由策略时选择 provider，否则选择 nodes；仅包含节点列表并附带其他键的文档会被拒绝，而不会被当作 provider 策略重新解释。`nodes` 仅导入节点，保留本地组和路由规则，不会创建选择组；`provider` 可替换允许的 provider、组和规则字段，必须逐项审阅。认证、listener 和 controller 凭据不在允许修改范围。

preview 保存私有候选，不激活配置、不重启。检查模式、变更字段、验证结果和候选 SHA256。公共 JSON 信封将 Controller 结果放在 `data.legacy`，preview 字段为 `data.legacy.id` 和 `data.legacy.sha256`。复制审阅过的 ID 和摘要：

```bash
mihomoctl subscription apply PREVIEW_ID --sha256 CANDIDATE_SHA256
mihomoctl config validate
mihomoctl restart
```

apply 校验活动原配置摘要、候选 SHA256、字段白名单，并使用 manager 指定的核心验证，再通过事务保存，成功后删除临时恢复材料。原配置漂移、候选篡改、越界修改或验证失败都会拒绝激活。配置发生改变后重新 preview。后续 provider 导入可能替换路由策略，需要再次检查自定义规则。不要编辑 preview 文件绕过门禁。
