"""Optional SSH/PTY frontend. All I/O belongs to application services."""
import json
import os
import threading
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Select, Static

try:
    from .controller_state import Store, Snapshot
    from .controller_types import ControlError
except ImportError:
    from controller_state import Store, Snapshot
    from controller_types import ControlError

PAGES = ("overview", "proxies", "connections", "rules", "logs", "profiles", "providers", "diagnostics", "runtime")
PAGE_NAMES = dict(zip(PAGES, ("首页", "节点", "连接", "规则", "日志", "订阅", "提供商", "诊断", "服务")))
GROUP_TYPES = {"Selector": "手动选择", "URLTest": "自动测速", "Fallback": "故障转移", "LoadBalance": "负载均衡"}
LABELS = {"state": "状态", "nodes": "节点数", "groups": "分组数", "rules": "规则数",
          "policy": "导入策略", "ignored_fields": "忽略的运行设置", "fields": "替换字段",
          "backup": "恢复备份", "service": "服务", "configuration": "配置", "added": "新增节点",
          "replaced": "替换节点", "removed": "移除节点", "removed_groups": "移除分组", "removed_rules": "移除规则",
          "group_changes": "提供商分组", "changes": "节点变化", "name": "名称", "type": "类型",
          "action": "操作", "selected": "当前选择", "error": "原因", "providers": "提供商",
          "controller": "控制器", "core": "核心", "mode": "模式", "connections": "连接数",
          "capabilities": "不可用功能", "pending_restart": "待重启", "endpoint": "端点",
          "up": "上传", "down": "下载", "inuse": "已用", "oslimit": "上限", "delay_ms": "延迟毫秒",
          "warning": "警告", "listener": "监听", "authentication": "身份验证"}
VALUES = {"preview": "预览（尚未保存）", "restart-required": "已保存，尚未生效，请重启",
          "unchanged": "未改变", "provider": "提供商节点、分组和规则", "nodes": "仅合并节点",
          "confirmed": "已完成", "add": "新增", "replace": "替换", "remove": "移除",
          "start": "启动", "stop": "停止", "restart": "重启"}
# Only these keys carry our own status enums. Node, group and provider names are
# user data and must survive translation verbatim.
STATUS_KEYS = frozenset(("state", "service", "policy", "action"))


def preview_count(preview, key):
    value = preview.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def preview_summary(preview):
    """Leading subscription lines: what arrives, then what the local copy loses.

    Kept short on purpose. At 80x24 the body is ten rows, so anything below the
    counts and the clearing warning is effectively invisible.
    """
    return [
        "状态 {}｜策略 {}".format(VALUES.get(str(preview.get("state", "")), str(preview.get("state", ""))) or "预览",
                                  VALUES.get(str(preview.get("policy", "")), str(preview.get("policy", ""))) or "提供商节点、分组和规则"),
        "节点 {}（新增 {}、替换 {}、移除 {}）｜分组 {}（移除 {}）｜规则 {}（移除 {}）".format(
            preview_count(preview, "nodes"), preview_count(preview, "added"),
            preview_count(preview, "replaced"), preview_count(preview, "removed"),
            preview_count(preview, "groups"), preview_count(preview, "removed_groups"),
            preview_count(preview, "rules"), preview_count(preview, "removed_rules"))]


def cleared_units(preview):
    """Report what a provider import would erase locally; never auto-downgrade."""
    units = []
    for key, unit in (("removed_groups", "个本地分组"), ("removed_rules", "条本地规则")):
        value = preview.get(key) if isinstance(preview, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            units.append("{} {}".format(value, unit))
    return units


def clearing_warnings(preview):
    units = cleared_units(preview)
    if not units:
        return []
    return ["警告：此预览会移除本地的" + "、".join(units) +
            "；提供商策略按订阅内容整体替换，不自动降级，保存后需用“恢复备份”回退。"]


def report_lines(value, prefix="", depth=0):
    """Render safe DTOs in readable prose, never rich markup or raw objects."""
    if depth > 5:
        return []
    if isinstance(value, dict):
        rows = []
        for key, child in value.items():
            if key in ("schema", "command"):
                continue
            title = LABELS.get(key, key.replace("_", " ").title())
            if isinstance(child, (dict, list)):
                rows.append(prefix + title)
                rows.extend(report_lines(child, prefix + "  ", depth + 1))
            else:
                text = str(child)
                rows.append(prefix + title + ": " + (VALUES.get(text, text) if key in STATUS_KEYS else text))
        return rows
    if isinstance(value, list):
        return [line for child in value for line in report_lines(child, prefix, depth + 1)]
    return [prefix + str(value)]


def human_bytes(value):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024

HELP = """首页：查看状态、初始化控制器、启动/停止/重启、切换运行模式。
节点：先选分组，再选节点；手动组回车切换，自动组由核心选择。
订阅：选择来源文件和导入策略 → 预览导入 → 保存 → 重启生效。
提供商策略：采用订阅自带的节点、分组和规则；缺少的策略字段会被清空（下方显示移除数量）。
仅合并节点：只按同名替换 proxies，分组与规则保留；订阅只含顶层 proxies 时使用。
本机监听、密钥、DNS 和 TUN 在两种策略下都保留。
更多：连接、规则、日志、提供商、诊断、服务。v 查看上次操作详情。
Tab / Shift+Tab 切换焦点；方向键浏览；Enter 确认；Esc 取消；q 退出。
/ 搜索；r 刷新；t 测速；T 批量测速（先确认）；[ / ] 切换分组。
p 暂停连接/日志；s 排序；m 手动组转换预览；o 可信脚本预览；y 保存。
高级命令（: 打开）：page NAME; start; stop; restart; mode rule|global|direct;
dns NAME [TYPE]; provider NAME; subscribe FILE; subscribe-url PRIVATE_URL_FILE;
diagnose url PUBLIC_HTTPS_URL; diagnose process PID; cancel; theme dark|light;
log-level debug|info|warning|error; journal; ready; doctor; codex; rules-status; rules-check.
subscribe 与 subscribe-url 使用订阅页当前选择的导入策略。
测速只探测公共 HTTPS 地址；重启会中断连接。私有详情需显式 --details。
"""


class Confirm(ModalScreen):
    DEFAULT_CSS = """
    Confirm { align: center middle; }
    Confirm > Vertical { width: 90%; height: 80%; max-height: 26; padding: 1 2; border: round $accent; background: $surface; }
    Confirm VerticalScroll { height: 1fr; min-height: 1; }
    Confirm Static { height: auto; }
    Confirm Horizontal { height: 3; }
    Confirm Button { width: 1fr; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message, accept="确认"):
        super().__init__()
        self.message, self.accept = message, accept

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll():
                yield Static(Text(self.message))
            with Horizontal():
                yield Button(self.accept, id="yes", variant="primary")
                yield Button("取消", id="no")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "yes")

    def action_cancel(self):
        self.dismiss(False)


class Console(App):
    TITLE = "mihomo-userctl"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #status { height: 2; }
    #navigation { height: 3; }
    #mainnav, #toolbar, #subscription-source { height: 3; }
    #mainnav Button, #toolbar Button { min-width: 8; width: auto; }
    #source-kind, #source-policy { width: 16; }
    #source-path { width: 1fr; }
    #mode-select { width: 16; }
    #search, #command { height: 3; }
    #proxies, #records, #body { height: 1fr; }
    #groups { width: 1fr; }
    #nodes { width: 2fr; }
    #hint { height: 1; }
    .compact Header { display: none; }
    .compact #status { height: 1; }
    .compact #groups { width: 2fr; }
    .compact #nodes { width: 3fr; }
    """
    BINDINGS = [Binding("q", "quit_console", "退出"), Binding("r", "refresh", "刷新"),
                Binding("ctrl+c", "quit_console", "退出", priority=True, show=False),
                Binding("/", "search", "搜索"), Binding("colon", "command", "命令", show=False),
                Binding("question_mark", "help", "帮助"), Binding("t", "latency", "测速", show=False),
                Binding("T", "batch", "批量测速", show=False), Binding("c", "connections", "连接", show=False),
                Binding("f", "traffic", "流量", show=False), Binding("p", "pause", "暂停"),
                Binding("s", "sort", "排序", show=False), Binding("m", "manual", "手动转换", show=False),
                Binding("v", "result", "详情"),
                Binding("o", "override", "脚本预览", show=False), Binding("y", "save", "保存", show=False),
                Binding("left_square_bracket", "previous_group", "上一分组", show=False),
                Binding("right_square_bracket", "next_group", "下一分组", show=False),
                Binding("escape", "cancel", "取消", show=False)]

    def __init__(self, service, ascii_only=False, theme="dark", initial_preview=None):
        super().__init__()
        self.service, self.ascii_only = service, ascii_only
        self.theme = "textual-light" if theme == "light" else "textual-dark"
        self.store = Store()
        self.page, self.group, self.node, self.filter_text = "profiles" if initial_preview else "overview", "", "", ""
        self.paused, self.reverse = False, False
        self.next_refresh, self.failures = {}, {}
        self.batch_cancel = threading.Event()
        self.preview = self.initial_preview = initial_preview
        if initial_preview:
            self.store.state.snapshots["operation"] = Snapshot(value=initial_preview, freshness="fresh")
        self.visible_nodes = []
        self.latencies = {}
        self.log_level = "info"
        self.exit_requested = False
        self.source_kind = "file"
        # A piped preview already decided the policy (tui --stdin --policy ...).
        # Seed the selector with it so the first Select.Changed is a no-op
        # instead of wiping the review the user just prepared.
        seeded = initial_preview.get("policy") if isinstance(initial_preview, dict) else None
        self.source_policy = seeded if seeded in ("provider", "nodes") else "provider"
        self.source_path = ""
        # Pending work and the guarded backup come from the service receipt, never
        # from a second copy the UI can drift on.
        self.pending_restart = bool(getattr(service, "pending_restart", False))
        self.last_backup = getattr(service, "backup", None) if self.pending_restart else None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("正在读取状态…", id="status", markup=False)
        with Horizontal(id="mainnav"):
            yield Button("首页", id="nav-overview")
            yield Button("节点", id="nav-proxies")
            yield Button("订阅", id="nav-profiles")
            yield Button("更多", id="nav-more")
        yield Select([(PAGE_NAMES[name], name) for name in PAGES], value=self.page, allow_blank=True, id="navigation")
        with Horizontal(id="subscription-source"):
            yield Select([("YAML 文件", "file"), ("URL 文件", "url")], value="file", allow_blank=False, id="source-kind")
            yield Select([("提供商策略", "provider"), ("仅合并节点", "nodes")], value=self.source_policy, allow_blank=False, id="source-policy")
            yield Input(placeholder="私有文件路径（不要输入订阅 URL）", id="source-path")
        with HorizontalScroll(id="toolbar"):
            yield Button("初始化", id="setup-controller")
            yield Button("启动", id="service-start")
            yield Button("停止", id="service-stop")
            yield Button("重启生效", id="service-restart")
            yield Select([("规则模式", "rule"), ("全局模式", "global"), ("直连模式", "direct")], prompt="切换模式", id="mode-select")
            yield Button("搜索", id="node-search")
            yield Button("测速", id="node-latency")
            yield Button("批量测速", id="node-batch")
            yield Button("预览导入", id="subscription-preview")
            yield Button("保存", id="subscription-save")
            yield Button("恢复备份", id="restore-backup")
        yield Input(placeholder="搜索（Esc 关闭）", id="search")
        with Horizontal(id="proxies"):
            yield DataTable(id="groups", cursor_type="row")
            yield DataTable(id="nodes", cursor_type="row")
        yield DataTable(id="records", cursor_type="row")
        yield RichLog(id="body", wrap=True, markup=False, max_lines=2000, auto_scroll=False)
        yield Static("先预览，再保存，最后重启生效；普通 Shell 保持直连", id="hint", markup=False)
        yield Input(placeholder="page proxies / start / dns example.com / subscribe FILE", id="command")
        yield Footer()

    def on_mount(self):
        self.query_one("#search").display = False
        self.query_one("#command").display = False
        self.query_one("#groups", DataTable).add_columns("分组", "方式", "当前选择")
        self.query_one("#nodes", DataTable).add_columns("节点", "当前", "延迟 ms")
        self._refresh_timer = self.set_interval(.1, self.tick)
        self.change_page("profiles" if self.preview else "overview")

    def on_resize(self, event):
        self.set_class(event.size.width < 80 or event.size.height < 24, "compact")
        if event.size.width < 60 or event.size.height < 14:
            self.query_one("#hint", Static).update("终端至少需要 60×14；可用 --engine plain 编号菜单")

    def on_unmount(self):
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()
        self.batch_cancel.set()
        self.store.close()

    def action_quit_console(self):
        self.batch_cancel.set()
        if "operation" in self.store.pending:
            self.exit_requested = True
            self.query_one("#hint", Static).update("正在取消排队测速；等待当前操作结束后退出")
            return
        self.exit()

    def sync_state(self):
        """Mirror the service receipt. A restart clears it, so recovery must follow."""
        self.pending_restart = bool(getattr(self.service, "pending_restart", False))
        self.last_backup = getattr(self.service, "backup", None) if self.pending_restart else None

    def apply_action_visibility(self):
        actions = self.page in ("overview", "profiles")
        self.query_one("#service-restart").display = actions
        self.query_one("#restore-backup").display = actions and bool(self.pending_restart and self.last_backup)

    def change_page(self, page):
        if self.page == "logs" and page != "logs":
            self.store.stop_stream("logs")
        self.page = self.store.state.page = page
        active = page if page in ("overview", "proxies", "profiles") else "more"
        for name in ("overview", "proxies", "profiles", "more"):
            self.query_one("#nav-" + name, Button).variant = "primary" if name == active else "default"
        self.query_one("#navigation").display = page not in ("overview", "proxies", "profiles")
        self.query_one("#subscription-source").display = page == "profiles"
        for identifier in ("setup-controller", "service-start", "service-stop", "mode-select"):
            self.query_one("#" + identifier).display = page == "overview"
        for identifier in ("node-search", "node-latency", "node-batch"):
            self.query_one("#" + identifier).display = page == "proxies"
        for identifier in ("subscription-preview", "subscription-save"):
            self.query_one("#" + identifier).display = page == "profiles"
        self.apply_action_visibility()
        self.paused = False
        self.query_one("#proxies").display = page == "proxies"
        self.query_one("#records").display = page in ("connections", "providers", "rules")
        self.query_one("#body").display = page not in ("proxies", "connections", "providers", "rules")
        self.query_one("#body", RichLog).auto_scroll = page == "logs"
        if page in ("connections", "providers", "rules"):
            table = self.query_one("#records", DataTable)
            table.clear(columns=True)
            columns = {"connections": ("链路", "规则", "上传", "下载"),
                       "providers": ("提供商", "类型", "节点", "更新时间"),
                       "rules": ("规则 / 提供商", "数量", "状态")}[page]
            table.add_columns(*columns)
        self.render_page()
        self.action_refresh()

    def on_select_changed(self, event):
        if event.select.id == "navigation" and event.value in PAGES:
            self.change_page(event.value)
        elif event.select.id == "mode-select" and event.value in ("rule", "global", "direct"):
            self.execute_command("mode " + event.value)
            event.select.clear()
        elif event.select.id == "source-kind":
            if event.value in ("file", "url") and event.value != self.source_kind:
                self.source_kind = event.value
                self.clear_preview("来源已切换，请重新预览导入。")
        elif event.select.id == "source-policy":
            if event.value in ("provider", "nodes") and event.value != self.source_policy:
                self.source_policy = event.value
                self.clear_preview("导入策略已切换，请重新预览导入。")

    def on_button_pressed(self, event):
        identifier = event.button.id
        if identifier and identifier.startswith("nav-"):
            page = identifier[4:]
            if page == "more":
                navigation = self.query_one("#navigation", Select)
                navigation.display = True
                # Blanking first makes re-picking the current page fire Changed;
                # a reactive set to its own value would be a silent no-op.
                navigation.clear()
                navigation.focus()
            else:
                self.query_one("#navigation", Select).value = page
                self.change_page(page)
        elif identifier == "setup-controller":
            self.push_screen(Confirm("为当前用户创建本机控制器和随机密钥？已有安全配置将保留。保存后需重启。"),
                             lambda yes: self.schedule("operation", self.service.initialize) if yes else None)
        elif identifier and identifier.startswith("service-"):
            self.execute_command(identifier.replace("service-", ""))
        elif identifier == "node-search":
            self.action_search()
        elif identifier == "node-latency":
            self.action_latency()
        elif identifier == "node-batch":
            self.action_batch()
        elif identifier == "subscription-preview":
            path = self.query_one("#source-path", Input).value.strip()
            url = self.query_one("#source-kind", Select).value == "url"
            policy = self.query_one("#source-policy", Select).value or self.source_policy
            if path:
                self.clear_preview()
                self.schedule("operation", lambda: self.service.subscription_preview(path, url=url, policy=policy))
            else:
                self.query_one("#hint", Static).update("请先填写私有 YAML 文件或 URL 文件的路径。")
        elif identifier == "subscription-save":
            self.action_save()
        elif identifier == "restore-backup":
            self.push_screen(Confirm("恢复上次保存前的配置？恢复后仍需重启。"),
                             lambda yes: self.schedule("operation", self.service.restore) if yes else None)

    def clear_preview(self, message=""):
        """Drop a stale preview and its seeded result so nothing else shows it."""
        self.preview = None
        snapshot = self.store.state.snapshots.get("operation")
        if snapshot is not None and "operation" not in self.store.pending and snapshot.value is self.initial_preview:
            self.store.state.snapshots.pop("operation", None)
        if message:
            self.query_one("#hint", Static).update(message)

    def schedule(self, key, operation):
        snapshot = self.store.state.snapshots.get(key)
        if key != "operation" and snapshot and snapshot.freshness == "unsupported":
            return
        if self.store.submit(key, operation):
            if key == "operation":
                self.query_one("#hint", Static).update("正在处理操作…")
                for identifier in ("source-path", "source-kind", "source-policy"):
                    self.query_one("#" + identifier).disabled = True

    def action_refresh(self):
        for key in (self.page, "traffic", "memory"):
            snapshot = self.store.state.snapshots.get(key)
            if snapshot and snapshot.freshness == "unsupported":
                snapshot.freshness = "stale"
        self.next_refresh[self.page] = time.monotonic() + 5
        if self.page == "logs" and hasattr(self.service, "logs"):
            self.store.stream("logs", lambda emit, stop: self.service.logs(emit, stop, self.log_level))
        else:
            self.schedule(self.page, lambda page=self.page: self.service.read(page))
        if self.page == "overview":
            self.schedule("runtime", lambda: self.service.read("runtime"))
            self.schedule("traffic", lambda: self.service.read("traffic"))
            self.schedule("memory", lambda: self.service.read("memory"))

    def tick(self):
        if self.store.closed or not self.query("#status"):
            return
        for key in self.store.drain():
            if key == "progress":
                completed, total = self.store.state.progress
                self.query_one("#hint", Static).update("批量测速 {}/{} | : cancel 停止排队项".format(completed, total))
                continue
            snap = self.store.state.snapshots[key]
            if snap.error:
                self.failures[key] = min(self.failures.get(key, 0) + 1, 5)
                self.next_refresh[key] = time.monotonic() + min(2 ** (self.failures[key] - 1), 15)
            else:
                self.failures[key] = 0
            if key == "operation":
                for identifier in ("source-path", "source-kind", "source-policy"):
                    self.query_one("#" + identifier).disabled = False
                self.sync_state()
                self.apply_action_visibility()
                if snap.value is not None and not snap.error:
                    result = snap.value
                    self.store.state.operations.append({key: value for key, value in result.items() if not isinstance(value, (list, dict))})
                    if result.get("state") == "preview":
                        self.preview = result
                    if result.get("action") in ("start", "restart"):
                        self.next_refresh["overview"] = 0
                    if "delay_ms" in result:
                        self.latencies[result["name"]] = result["delay_ms"]
                    for row in result.get("results", []):
                        if "delay_ms" in row:
                            self.latencies[row["name"]] = row["delay_ms"]
                    if result.get("state") == "preview":
                        summary = " | ".join(preview_summary(result))
                        cleared = cleared_units(result)
                        summary += " | 点击保存，确认后重启生效" + ("（会清空本地" + "、".join(cleared) + "）" if cleared else "")
                    else:
                        summary = " | ".join(line.strip() for line in report_lines(result)[:3])
                    self.query_one("#hint", Static).update(Text(summary))
                else:
                    self.query_one("#hint", Static).update("操作未完成：" + snap.error + ("；可点击恢复备份，再重启" if self.pending_restart and self.last_backup else "；请检查核心与私有配置"))
            if key == "logs" and not snap.error and not hasattr(self.service, "logs"):
                self.store.state.logs.append(snap.value)
            if (key == self.page or key in ("operation", "runtime", "traffic", "memory")) and not (self.paused and self.page in ("logs", "connections")):
                self.render_page()
        if self.exit_requested:
            if "operation" not in self.store.pending:
                self.exit()
            return
        if self.page == "overview" and time.monotonic() >= self.next_refresh.get("traffic", 0):
            self.next_refresh["traffic"] = time.monotonic() + 1
            self.schedule("traffic", lambda: self.service.read("traffic"))
        if self.paused or self.page in ("profiles", "rules", "providers", "diagnostics"):
            return
        now = time.monotonic()
        if self.page == "logs" and hasattr(self.service, "logs"):
            snapshot = self.store.state.snapshots.get("logs")
            if not snapshot or snapshot.freshness != "unsupported":
                self.store.stream("logs", lambda emit, stop: self.service.logs(emit, stop, self.log_level))
            return
        if now >= self.next_refresh.get(self.page, 0):
            interval = 2 if self.page == "connections" else 1 if self.page == "logs" else 5
            self.next_refresh[self.page] = now + interval
            self.schedule(self.page, lambda page=self.page: self.service.read(page))
            if self.page == "overview":
                self.schedule("runtime", lambda: self.service.read("runtime"))
                self.schedule("memory", lambda: self.service.read("memory"))

    def replace_rows(self, table, rows):
        old_key = None
        old_scroll = table.scroll_y
        if table.row_count and table.cursor_row < table.row_count:
            old_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        table.clear()
        for key, values in rows:
            table.add_row(*(Text(str(value)) for value in values), key=key)
        if old_key in table.rows:
            table.move_cursor(row=table.get_row_index(old_key), animate=False, scroll=False)
            table.scroll_to(y=old_scroll, animate=False, force=True)

    def render_page(self):
        snap = self.store.state.snapshots.get(self.page)
        if not snap:
            self.query_one("#status", Static).update(PAGE_NAMES[self.page] + "：正在读取…")
            return
        sampled = time.strftime("%H:%M:%S", time.localtime(snap.sampled_at)) if snap.sampled_at else "never"
        self.query_one("#status", Static).update(Text("{}：{} | 更新于 {} | {}{}".format(
            PAGE_NAMES[self.page], {"fresh": "已更新", "stale": "旧数据", "unsupported": "核心不支持"}.get(snap.freshness, snap.freshness), sampled, snap.error, " | 已暂停" if self.paused else "")))
        value = snap.value
        if value is None:
            self.query_one("#body", RichLog).clear()
            self.query_one("#body", RichLog).write(Text("暂不可用。可回首页初始化控制器、启动或重启；服务与诊断仍可使用。 " + snap.error))
            self.query_one("#hint", Static).update("当前核心不支持此功能；其他页面仍可使用，r 重新检查。" if snap.freshness == "unsupported" else "连接或配置未就绪；回首页初始化、启动或重启。")
            return
        if self.page == "proxies":
            groups = [row for row in value.values() if "members" in row]
            if self.group not in [row["name"] for row in groups]:
                self.group = groups[0]["name"] if groups else ""
            self.replace_rows(self.query_one("#groups", DataTable), [(row["name"], (row["name"], GROUP_TYPES.get(row["type"], row["type"]), row["selected"] or "")) for row in groups])
            group = value.get(self.group, {})
            self.visible_nodes = sorted([node for node in group.get("members", []) if self.filter_text.casefold() in node.casefold()], key=str.casefold, reverse=self.reverse)
            marker = "*" if self.ascii_only else "✓"
            self.replace_rows(self.query_one("#nodes", DataTable), [(node, (node, marker if node == group.get("selected") else "", self.latencies.get(node, ""))) for node in self.visible_nodes])
            self.query_one("#nodes").border_title = self.group + (" [回车选择]" if group.get("selectable") else " [自动组，只读]")
            self.query_one("#hint", Static).update("回车选择分组/节点；自动测速、故障转移组由核心决定节点" if group.get("selectable") else "此组由核心自动选择节点；可测速，不能手动切换")
        elif self.page == "connections":
            rows = []
            for index, row in enumerate(value["connections"]):
                route = " > ".join(row["chains"])
                if self.filter_text.casefold() in (route + row["rule"] + row.get("host", "")).casefold():
                    rows.append((row.get("id", str(index)), (route + (" | " + row["host"] if self.service.details else ""), row["rule"], row["upload"], row["download"])))
            rows.sort(key=lambda row: row[1][3], reverse=self.reverse)
            self.replace_rows(self.query_one("#records", DataTable), rows)
        elif self.page == "providers":
            self.replace_rows(self.query_one("#records", DataTable), [(row["name"], (row["name"], row["type"], row["nodes"], row["updated"])) for row in value["providers"] if self.filter_text.casefold() in row["name"].casefold()])
        elif self.page == "rules":
            rows = [("type:" + name, (name, count, "runtime rule")) for name, count in value["types"].items() if self.filter_text.casefold() in name.casefold()]
            rows.extend(("provider:" + row["name"], (row["name"], row["rules"], row["behavior"] + " | " + row["updated"])) for row in value.get("providers", []) if self.filter_text.casefold() in row["name"].casefold())
            self.replace_rows(self.query_one("#records", DataTable), rows)
            self.query_one("#hint", Static).update("规则提供商：" + value.get("provider_capability", "未知") + " | : rules-status / rules-check")
        else:
            body = self.query_one("#body", RichLog)
            body.clear()
            if self.page == "logs":
                for row in self.store.state.logs:
                    if self.filter_text.casefold() in json.dumps(row).casefold():
                        body.write(Text("{}  {}".format(row.get("level", "info"), row.get("message", ""))))
            elif self.page == "overview":
                runtime = self.store.state.snapshots.get("runtime")
                traffic = self.store.state.snapshots.get("traffic")
                memory = self.store.state.snapshots.get("memory")
                body.write(Text("当前用户的代理服务", style="bold"))
                body.write(Text("配置：" + ("已保存，尚未生效，请点击重启生效" if self.pending_restart or value.get("pending_restart") else "无本次待生效更改")))
                if value.get("controller") == "unavailable":
                    body.write(Text("控制器尚未连接：" + value.get("error", "未知")))
                    body.write(Text("已有配置：点击初始化，再重启。缺少配置或核心：请先完成安装与私有配置。"))
                    body.write(Text("已有非本机监听或无效密钥不会被覆盖，请修正后重试。"))
                if runtime:
                    body.write(Text("服务状态：{} {}".format((runtime.value or {}).get("service", runtime.freshness), runtime.error)))
                listener = value.get("listener", "UNVERIFIED") if snap.freshness == "fresh" else "UNVERIFIED (stale)"
                authentication = value.get("authentication", "UNVERIFIED") if snap.freshness == "fresh" else "UNVERIFIED (stale)"
                body.write(Text("本机监听：{} | 身份验证：{}".format(listener, authentication)))
                body.write(Text("核心：{} | 模式：{} | 连接数：{}".format(value.get("core", "未知"), value.get("mode", "未知"), value.get("connections", "未知"))))
                if traffic and traffic.value:
                    body.write(Text("流量：上传 {}/s | 下载 {}/s".format(human_bytes(traffic.value["up"]), human_bytes(traffic.value["down"]))))
                if memory and memory.value:
                    body.write(Text("内存：{}".format(human_bytes(memory.value["inuse"]))))
                for feature, error in value.get("capabilities", {}).items():
                    body.write(Text("功能 {} 暂不可用：{}".format(feature, error)))
                self.query_one("#mode-select").disabled = "mode" in value.get("capabilities", {}) or value.get("controller") == "unavailable"
                body.write(Text("\n当前节点选择", style="bold"))
                for group in value.get("groups", []):
                    body.write(Text("{} [{}]  →  {}".format(group["name"], GROUP_TYPES.get(group["type"], group["type"]), group.get("selected") or "自动")))
                body.write(Text("\n最近操作", style="bold"))
                for operation in list(self.store.state.operations)[-5:]:
                    body.write(Text(" | ".join(report_lines(operation)[:3])))
                body.write(Text("更多 → 服务/诊断可查看详细状态；v 查看上次操作详情。"))
            elif self.page == "profiles":
                body.write(Text("订阅：预览 → 保存 → 重启生效；策略默认提供商，可切换“仅合并节点”", style="bold"))
                if self.pending_restart:
                    body.write(Text("已保存，尚未生效：点击重启生效；失败时可恢复备份。", style="bold"))
                if self.preview:
                    for line in preview_summary(self.preview):
                        body.write(Text(line))
                    for line in clearing_warnings(self.preview):
                        body.write(Text(line, style="bold"))
                    ignored = [str(row) for row in (self.preview.get("ignored_fields") or [])]
                    body.write(Text("忽略的运行设置：" + ("、".join(ignored) if ignored else "无")))
                    body.write(Text("保存将写入此预览；v 查看完整变化。"))
                else:
                    body.write(Text("提供商策略＝订阅自带的节点/分组/规则，缺少的字段会清空；仅合并节点＝只按同名替换 proxies。"))
                    body.write(Text("本机端口、控制器、密钥、DNS、TUN 始终保留；文件权限应为 600。"))
                    body.write(Text("标准输入导入：mihomoctl tui --stdin < 私有订阅.yaml"))
                    body.write(Text("当前配置：{}｜节点 {}｜分组 {}｜提供商 {}".format(
                        value.get("configuration", "private"), value.get("nodes", 0),
                        value.get("groups", 0), value.get("providers", 0))))
            else:
                for line in report_lines(value):
                    body.write(Text(line))

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "groups":
            self.group = event.row_key.value
            self.render_page()
            self.query_one("#nodes").focus()
        elif event.data_table.id == "nodes":
            node, group = event.row_key.value, self.group
            self.node = node
            snapshot = self.store.state.snapshots.get("proxies")
            if not snapshot or not (snapshot.value or {}).get(group, {}).get("selectable"):
                self.query_one("#hint", Static).update("自动组由核心选择节点，可使用测速。")
                return
            self.push_screen(Confirm("将 {} 切换为 {}？已有连接保持打开。".format(group, node)),
                             lambda yes: self.schedule("operation", lambda: self.service.choose(group, node)) if yes else None)

    def selected_node(self):
        table = self.query_one("#nodes", DataTable)
        if self.page != "proxies" or not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def action_latency(self):
        node = self.selected_node()
        if node:
            self.schedule("operation", lambda: self.service.latency(node))

    def action_batch(self):
        targets = tuple(self.visible_nodes) if self.page == "proxies" else ()
        if targets:
            self.push_screen(Confirm("对当前可见的 {} 个节点测速？目标为公共 HTTPS 地址，最多 4 个并发；: cancel 停止排队项。".format(len(targets))),
                             lambda yes: self.start_batch(targets) if yes else None)

    def start_batch(self, targets):
        if "operation" not in self.store.pending:
            self.batch_cancel = threading.Event()
            cancelled = self.batch_cancel
            self.schedule("operation", lambda: self.service.batch_latency(targets, cancelled, self.store.progress))

    def action_connections(self):
        self.query_one("#navigation", Select).value = "connections"

    def action_traffic(self):
        self.schedule("operation", lambda: self.service.read("traffic"))

    def action_manual(self):
        if self.page == "proxies" and self.group:
            self.schedule("operation", lambda group=self.group: self.service.policy(group=group))

    def action_override(self):
        if self.service.script:
            self.schedule("operation", lambda: self.service.policy())

    def action_save(self):
        preview = self.preview
        if not preview:
            self.query_one("#hint", Static).update("请先预览，再保存；修改来源或策略后需重新预览。")
            return
        def save(yes):
            if yes:
                self.preview = None
                if "id" in preview:
                    self.schedule("operation", lambda: self.service.subscription_apply(preview["id"], preview["sha256"]))
                else:
                    self.schedule("operation", lambda: self.service.policy(apply=True))
        message = "校验、备份并保存此预览？保存后需单独重启生效。\n" + "\n".join(report_lines(preview))
        warnings = clearing_warnings(preview)
        if warnings:
            message += "\n\n" + "\n".join(warnings)
        self.push_screen(Confirm(message), save)

    def action_search(self):
        widget = self.query_one("#search", Input)
        widget.display = True
        widget.focus()

    def on_input_changed(self, event):
        if event.input.id == "search":
            self.filter_text = self.store.state.query = event.value
            self.render_page()
        elif event.input.id == "source-path":
            if event.value != self.source_path:
                self.source_path = event.value
                self.clear_preview()

    def action_command(self):
        widget = self.query_one("#command", Input)
        widget.display = True
        widget.focus()

    def on_input_submitted(self, event):
        if event.input.id == "search":
            event.input.display = False
            self.query_one("#nodes" if self.page == "proxies" else "#navigation").focus()
        elif event.input.id == "command":
            command = event.value.strip()
            event.input.value = ""
            event.input.display = False
            self.execute_command(command)

    def execute_command(self, command):
        verb, _, rest = command.partition(" ")
        if verb == "page" and rest in PAGES:
            self.query_one("#navigation", Select).value = rest
        elif verb == "group" and rest:
            snapshot = self.store.state.snapshots.get("proxies")
            if snapshot and snapshot.value and "members" in snapshot.value.get(rest, {}):
                self.group = rest
                self.render_page()
        elif verb in ("start", "stop", "restart") and not rest:
            self.push_screen(Confirm("确认{}当前用户的代理服务？".format({"start": "启动", "stop": "停止", "restart": "重启"}[verb])),
                             lambda yes: self.schedule("operation", lambda: self.service.shell(verb)) if yes else None)
        elif verb == "mode" and rest in ("rule", "global", "direct"):
            self.push_screen(Confirm("切换核心运行模式为 {}？此操作不保存到配置文件。".format(rest)),
                             lambda yes: self.schedule("operation", lambda: self.service.mode(rest)) if yes else None)
        elif verb == "provider" and rest:
            self.push_screen(Confirm("下载/刷新提供商 {}？".format(rest)),
                             lambda yes: self.schedule("operation", lambda: self.service.provider_refresh(rest)) if yes else None)
        elif verb in ("subscribe", "subscribe-url") and rest:
            policy = self.source_policy
            self.schedule("operation", lambda: self.service.subscription_preview(rest, url=verb == "subscribe-url", policy=policy))
        elif verb == "dns" and 1 <= len(rest.split()) <= 2:
            arguments = rest.split()
            self.schedule("operation", lambda: self.service.dns(*arguments))
        elif verb == "diagnose":
            kind, _, target = rest.partition(" ")
            if kind in ("url", "process") and target:
                self.schedule("operation", lambda: self.service.diagnose(kind, target))
            else:
                self.query_one("#hint", Static).update("用法：diagnose url 公网HTTPS地址 或 diagnose process PID")
        elif verb in ("doctor", "ready", "codex", "rules-status", "rules-check") and not rest:
            self.schedule("operation", lambda: self.service.shell(verb))
        elif verb == "journal" and not rest:
            self.schedule("operation", self.service.journal)
        elif verb == "cancel":
            self.batch_cancel.set()
        elif verb == "theme" and rest in ("dark", "light"):
            self.theme = "textual-light" if rest == "light" else "textual-dark"
        elif verb == "log-level" and rest in ("debug", "info", "warning", "error"):
            self.log_level = rest
            self.store.stop_stream("logs")
        else:
            self.query_one("#hint", Static).update("未知命令；按 ? 查看可用命令")

    def action_pause(self):
        if self.page in ("logs", "connections"):
            self.paused = not self.paused
            self.render_page()

    def action_sort(self):
        self.reverse = not self.reverse
        self.render_page()

    def move_group(self, delta):
        snapshot = self.store.state.snapshots.get("proxies")
        if self.page == "proxies" and snapshot and snapshot.value:
            groups = [name for name, row in snapshot.value.items() if "members" in row]
            if groups:
                index = groups.index(self.group) if self.group in groups else 0
                self.group = groups[(index + delta) % len(groups)]
                self.render_page()

    def action_previous_group(self):
        self.move_group(-1)

    def action_next_group(self):
        self.move_group(1)

    def action_help(self):
        self.push_screen(Confirm(HELP, "关闭"))

    def action_result(self):
        result = self.store.state.snapshots.get("operation")
        if result and result.value:
            warnings = clearing_warnings(result.value)
            self.push_screen(Confirm("\n".join(report_lines(result.value) + warnings), "关闭"))
        elif result and result.error:
            self.push_screen(Confirm("操作未完成：" + result.error + "\n请检查核心、私有配置和控制器设置后重试。" +
                                     ("\n重启失败时可点击恢复备份，再重启。" if self.pending_restart and self.last_backup else ""), "关闭"))

    def action_cancel(self):
        for identifier in ("search", "command"):
            widget = self.query_one("#" + identifier, Input)
            if widget.display:
                widget.display = False
                self.query_one("#navigation").focus()
                return
        if self.preview is not None:
            self.clear_preview("已取消当前预览；重新预览后才能保存。")
            self.render_page()
        self.batch_cancel.set()


def run(service, ascii_only=False, theme="dark", initial_preview=None):
    import sys
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    Console(service, ascii_only=ascii_only, theme=theme, initial_preview=initial_preview).run(mouse=True)
    return {"state": "closed", "shell": "unchanged"}
