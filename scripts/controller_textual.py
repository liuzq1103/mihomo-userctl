"""Optional SSH/PTY frontend. All I/O belongs to application services."""
import json
import os
import threading
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Select, Static

try:
    from .controller_state import Store
    from .controller_types import ControlError
except ImportError:
    from controller_state import Store
    from controller_types import ControlError

PAGES = ("overview", "proxies", "connections", "rules", "logs", "profiles", "providers", "diagnostics", "runtime")


def report_lines(value, prefix="", depth=0):
    """Render safe DTOs in readable prose, never rich markup or raw objects."""
    if depth > 5:
        return []
    if isinstance(value, dict):
        rows = []
        for key, child in value.items():
            if key in ("schema", "command"):
                continue
            title = key.replace("_", " ").title()
            if isinstance(child, (dict, list)):
                rows.append(prefix + title)
                rows.extend(report_lines(child, prefix + "  ", depth + 1))
            else:
                rows.append(prefix + title + ": " + str(child))
        return rows
    if isinstance(value, list):
        return [line for child in value for line in report_lines(child, prefix, depth + 1)]
    return [prefix + str(value)]


def human_bytes(value):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return "{:.1f} {}".format(value, unit)
        value /= 1024

HELP = """Keyboard: Tab / Shift+Tab focus; arrows navigate; Enter choose group/node.
/ search; r refresh; t node latency; T batch of visible nodes (confirm first).
c connections; f traffic; m manual group preview; o trusted JS preview; y save preview.
[ / ] previous/next group (also in compact layout); command: group NAME.
p pause connections/logs; s sort; : commands; ? help; Esc cancel; q quit.
v opens the full last operation result.
Commands: page NAME; start; stop; restart; mode rule|global|direct; dns NAME [TYPE];
provider NAME; subscribe FILE; subscribe-url PRIVATE_URL_FILE; cancel; theme dark|light;
diagnose url PUBLIC_HTTPS_URL; diagnose process PID;
log-level debug|info|warning|error; journal; ready; doctor; codex; rules-status; rules-check.
Subscriptions only merge nodes. y validates, backs up and saves; restart separately.
Latency is a public HTTPS probe, not a model E2E check. Existing connections stay open.
Private hosts/rule details/log messages require --details. Nothing changes the parent shell.
"""


class Confirm(ModalScreen):
    DEFAULT_CSS = """
    Confirm { align: center middle; }
    Confirm > Vertical { width: 90%; height: auto; max-height: 90%; padding: 1 2; border: round $accent; background: $surface; }
    Confirm VerticalScroll { height: auto; max-height: 16; }
    Confirm Static { height: auto; }
    Confirm Horizontal { height: 3; }
    Confirm Button { width: 1fr; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message, accept="Confirm"):
        super().__init__()
        self.message, self.accept = message, accept

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll():
                yield Static(Text(self.message))
            with Horizontal():
                yield Button(self.accept, id="yes", variant="primary")
                yield Button("Cancel", id="no")

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
    #search, #command { height: 3; }
    #proxies, #records, #body { height: 1fr; }
    #groups { width: 1fr; }
    #nodes { width: 2fr; }
    #hint { height: 1; }
    .compact Header { display: none; }
    .compact #status { height: 1; }
    .compact #groups { display: none; }
    """
    BINDINGS = [Binding("q", "quit_console", "Quit"), Binding("r", "refresh", "Refresh"),
                Binding("ctrl+c", "quit_console", "Quit", priority=True, show=False),
                Binding("/", "search", "Search"), Binding("colon", "command", "Commands"),
                Binding("question_mark", "help", "Help"), Binding("t", "latency", "Latency"),
                Binding("T", "batch", "Batch"), Binding("c", "connections", "Connections", show=False),
                Binding("f", "traffic", "Traffic", show=False), Binding("p", "pause", "Pause"),
                Binding("s", "sort", "Sort", show=False), Binding("m", "manual", "Manual", show=False),
                Binding("v", "result", "Result"),
                Binding("o", "override", "Override", show=False), Binding("y", "save", "Save", show=False),
                Binding("left_square_bracket", "previous_group", "Previous group", show=False),
                Binding("right_square_bracket", "next_group", "Next group", show=False),
                Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, service, ascii_only=False, theme="dark"):
        super().__init__()
        self.service, self.ascii_only = service, ascii_only
        self.theme = "textual-light" if theme == "light" else "textual-dark"
        self.store = Store()
        self.page, self.group, self.node, self.filter_text = "overview", "", "", ""
        self.paused, self.reverse = False, False
        self.next_refresh, self.failures = {}, {}
        self.batch_cancel = threading.Event()
        self.preview = None
        self.visible_nodes = []
        self.latencies = {}
        self.log_level = "info"
        self.exit_requested = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading; safety checks are not yet verified", id="status", markup=False)
        yield Select([(name.title(), name) for name in PAGES], value="overview", allow_blank=False, id="navigation")
        yield Input(placeholder="Search (Esc closes)", id="search")
        with Horizontal(id="proxies"):
            yield DataTable(id="groups", cursor_type="row")
            yield DataTable(id="nodes", cursor_type="row")
        yield DataTable(id="records", cursor_type="row")
        yield RichLog(id="body", wrap=True, markup=False, max_lines=2000)
        yield Static("? help | : commands | ordinary shell remains direct", id="hint", markup=False)
        yield Input(placeholder="page proxies / start / dns example.com / subscribe FILE", id="command")
        yield Footer()

    def on_mount(self):
        self.query_one("#search").display = False
        self.query_one("#command").display = False
        self.query_one("#groups", DataTable).add_columns("Group", "Type", "Selected")
        self.query_one("#nodes", DataTable).add_columns("Node", "Selected", "Latency ms")
        self._refresh_timer = self.set_interval(.1, self.tick)
        self.change_page("overview")

    def on_resize(self, event):
        self.set_class(event.size.width < 80 or event.size.height < 24, "compact")
        if event.size.width < 60 or event.size.height < 14:
            self.query_one("#hint", Static).update("Terminal needs 60x14; use --engine plain or CLI")

    def on_unmount(self):
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()
        self.batch_cancel.set()
        self.store.close()

    def action_quit_console(self):
        self.batch_cancel.set()
        if "operation" in self.store.pending:
            self.exit_requested = True
            self.query_one("#hint", Static).update("Cancelling queued tests; waiting for the active operation before exit")
            return
        self.exit()

    def change_page(self, page):
        if self.page == "logs" and page != "logs":
            self.store.stop_stream("logs")
        self.page = self.store.state.page = page
        self.paused = False
        self.query_one("#proxies").display = page == "proxies"
        self.query_one("#records").display = page in ("connections", "providers", "rules")
        self.query_one("#body").display = page not in ("proxies", "connections", "providers", "rules")
        if page in ("connections", "providers", "rules"):
            table = self.query_one("#records", DataTable)
            table.clear(columns=True)
            columns = {"connections": ("Route", "Rule", "Upload", "Download"),
                       "providers": ("Provider", "Type", "Nodes", "Updated"),
                       "rules": ("Rule / Provider", "Count", "Status")}[page]
            table.add_columns(*columns)
        self.render_page()
        self.action_refresh()

    def on_select_changed(self, event):
        if event.select.id == "navigation" and event.value in PAGES:
            self.change_page(event.value)

    def schedule(self, key, operation):
        if self.store.submit(key, operation):
            self.query_one("#hint", Static).update("Working: " + key + " (UI remains responsive)")

    def action_refresh(self):
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
                self.query_one("#hint", Static).update("Batch latency: {}/{} | : cancel stops queued tests".format(completed, total))
                continue
            snap = self.store.state.snapshots[key]
            if snap.error:
                self.failures[key] = min(self.failures.get(key, 0) + 1, 5)
                self.next_refresh[key] = time.monotonic() + min(2 ** (self.failures[key] - 1), 15)
            else:
                self.failures[key] = 0
            if key == "operation":
                if snap.value is not None and not snap.error:
                    result = snap.value
                    self.store.state.operations.append({key: value for key, value in result.items() if not isinstance(value, (list, dict))})
                    if result.get("state") == "preview":
                        self.preview = result
                    if "delay_ms" in result:
                        self.latencies[result["name"]] = result["delay_ms"]
                    for row in result.get("results", []):
                        if "delay_ms" in row:
                            self.latencies[row["name"]] = row["delay_ms"]
                    summary = " | ".join(line.strip() for line in report_lines(result)[:3])
                    self.query_one("#hint", Static).update(Text(summary + (" | y review/save" if result.get("state") == "preview" else "")))
                else:
                    self.query_one("#hint", Static).update("Operation failed: " + snap.error)
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
            self.query_one("#status", Static).update(self.page + ": loading / UNVERIFIED")
            return
        sampled = time.strftime("%H:%M:%S", time.localtime(snap.sampled_at)) if snap.sampled_at else "never"
        self.query_one("#status", Static).update(Text("{}: {} | sampled {} | {}{}".format(
            self.page, snap.freshness, sampled, snap.error, " | PAUSED" if self.paused else "")))
        value = snap.value
        if value is None:
            self.query_one("#body", RichLog).clear()
            self.query_one("#body", RichLog).write(Text("Unavailable. Configure the private loopback Controller for API pages; runtime/diagnostics remain usable. " + snap.error))
            return
        if self.page == "proxies":
            groups = [row for row in value.values() if "members" in row]
            if self.group not in [row["name"] for row in groups]:
                self.group = groups[0]["name"] if groups else ""
            self.replace_rows(self.query_one("#groups", DataTable), [(row["name"], (row["name"], row["type"], row["selected"] or "")) for row in groups])
            group = value.get(self.group, {})
            self.visible_nodes = sorted([node for node in group.get("members", []) if self.filter_text.casefold() in node.casefold()], key=str.casefold, reverse=self.reverse)
            marker = "*" if self.ascii_only else "✓"
            self.replace_rows(self.query_one("#nodes", DataTable), [(node, (node, marker if node == group.get("selected") else "", self.latencies.get(node, ""))) for node in self.visible_nodes])
            self.query_one("#nodes").border_title = self.group + (" [manual]" if group.get("selectable") else " [automatic/read-only]")
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
            self.query_one("#hint", Static).update("Rule providers: " + value.get("provider_capability", "unknown") + " | : rules-status / rules-check")
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
                body.write(Text("USER RUNTIME", style="bold"))
                if runtime:
                    body.write(Text("Service observation: {} {}".format(runtime.freshness, runtime.error)))
                    for line in report_lines(runtime.value or {}):
                        body.write(Text("  " + line))
                listener = value.get("listener", "UNVERIFIED") if snap.freshness == "fresh" else "UNVERIFIED (stale)"
                authentication = value.get("authentication", "UNVERIFIED") if snap.freshness == "fresh" else "UNVERIFIED (stale)"
                body.write(Text("Controller listener: {} | Authentication: {} | Readiness: UNVERIFIED".format(listener, authentication)))
                body.write(Text("Core: {} | Active connections: {}".format(value.get("core", "unknown"), value.get("connections", "unknown"))))
                if traffic and traffic.value:
                    body.write(Text("Traffic [{}]: upload {}/s | download {}/s".format(traffic.freshness, human_bytes(traffic.value["up"]), human_bytes(traffic.value["down"]))))
                if memory and memory.value:
                    body.write(Text("Memory [{}]: {}".format(memory.freshness, human_bytes(memory.value["inuse"]))))
                body.write(Text("\nCURRENT SELECTIONS", style="bold"))
                for group in value.get("groups", []):
                    body.write(Text("{} [{}]  >  {}".format(group["name"], group["type"], group.get("selected") or "dynamic")))
                body.write(Text("\nRECENT OPERATIONS", style="bold"))
                for operation in list(self.store.state.operations)[-5:]:
                    body.write(Text(" | ".join(report_lines(operation)[:3])))
                body.write(Text("Use : ready for explicit authenticated readiness; ? for all controls."))
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
            self.push_screen(Confirm("Select {} in {}? Existing connections remain open.".format(node, group)),
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
            self.push_screen(Confirm("Test {} visible nodes against the public HTTPS target? Up to 4 concurrent tests; : cancel stops queued tests.".format(len(targets))),
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
            return
        def save(yes):
            if yes:
                self.preview = None
                if "id" in preview:
                    self.schedule("operation", lambda: self.service.subscription_apply(preview["id"], preview["sha256"]))
                else:
                    self.schedule("operation", lambda: self.service.policy(apply=True))
        self.push_screen(Confirm("Validate, back up and save this preview? Service stays unchanged; restart separately.\n" + "\n".join(report_lines(preview))), save)

    def action_search(self):
        widget = self.query_one("#search", Input)
        widget.display = True
        widget.focus()

    def on_input_changed(self, event):
        if event.input.id == "search":
            self.filter_text = self.store.state.query = event.value
            self.render_page()

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
            self.push_screen(Confirm("{} the current user's service?".format(verb)),
                             lambda yes: self.schedule("operation", lambda: self.service.shell(verb)) if yes else None)
        elif verb == "mode" and rest in ("rule", "global", "direct"):
            self.push_screen(Confirm("Change the core's runtime routing mode to {}? The shell and disk configuration stay unchanged.".format(rest)),
                             lambda yes: self.schedule("operation", lambda: self.service.mode(rest)) if yes else None)
        elif verb == "provider" and rest:
            self.push_screen(Confirm("Download/refresh provider {}?".format(rest)),
                             lambda yes: self.schedule("operation", lambda: self.service.provider_refresh(rest)) if yes else None)
        elif verb in ("subscribe", "subscribe-url") and rest:
            self.schedule("operation", lambda: self.service.subscription_preview(rest, url=verb == "subscribe-url"))
        elif verb == "dns" and 1 <= len(rest.split()) <= 2:
            arguments = rest.split()
            self.schedule("operation", lambda: self.service.dns(*arguments))
        elif verb == "diagnose":
            kind, _, target = rest.partition(" ")
            if kind in ("url", "process") and target:
                self.schedule("operation", lambda: self.service.diagnose(kind, target))
            else:
                self.query_one("#hint", Static).update("Use diagnose url PUBLIC_HTTPS_URL or diagnose process PID")
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
            self.query_one("#hint", Static).update("Unknown command; ? shows available commands")

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
        self.push_screen(Confirm(HELP, "Close"))

    def action_result(self):
        result = self.store.state.snapshots.get("operation")
        if result and result.value:
            self.push_screen(Confirm("\n".join(report_lines(result.value)), "Close"))

    def action_cancel(self):
        for identifier in ("search", "command"):
            widget = self.query_one("#" + identifier, Input)
            if widget.display:
                widget.display = False
                self.query_one("#navigation").focus()
                return
        self.preview = None
        self.batch_cancel.set()


def run(service, ascii_only=False, theme="dark"):
    import sys
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    Console(service, ascii_only=ascii_only, theme=theme).run(mouse=True)
    return {"state": "closed", "shell": "unchanged"}
