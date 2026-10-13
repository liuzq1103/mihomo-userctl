# 控制台

`mihomoctl tui` 默认在有 Textual 时使用该界面，否则使用纯终端菜单；也可显式 `mihomoctl tui --engine plain`。Textual 属于可选依赖，须在控制层使用的解释器中安装发行版 tui extra 或核验后的依赖。界面不会隐式下载 Python 环境。

订阅、规则和策略事务使用相同 manager、核心路径和安全门禁。详见 [订阅](subscriptions.md)、[规则](rules.md) 和 [命令参考](reference/cli.md)。本地 JS override 只能执行可信代码，Node vm 不是沙箱。
