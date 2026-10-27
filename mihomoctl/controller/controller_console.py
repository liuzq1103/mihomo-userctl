"""User-level controller component; no global proxy or daemon."""
import os
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import unicodedata
try:
    from . import files
except ImportError:
    import files
try:
    from .controller_types import ControlError, error_text, TUI_INSTALL_COMMAND
    from .controller_service import select, snapshot, latency_target as measure_delay
    from .controller_policy import policy_candidate
    from .controller_transaction import apply_policy
    from .controller_health import guidance, parse_console
except ImportError:
    from controller_types import ControlError, error_text, TUI_INSTALL_COMMAND
    from controller_service import select, snapshot, latency_target as measure_delay
    from controller_policy import policy_candidate
    from controller_transaction import apply_policy
    from controller_health import guidance, parse_console

def describe(value):
    """One-line rendering for a status field; unknown stays visible as unknown."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join("{}={}".format(name, describe(item)) for name, item in list(value.items())[:8]) or "unknown"
    if isinstance(value, list):
        return " | ".join(describe(item) for item in value[:8])
    return str(value)


def plain_console(service, initial_preview=None):
    """Dependency-free task menu; controller failures do not prevent setup."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    def confirm(message):
        return input(message + " [y/N]: ").strip().lower() == "y"

    def clearing_warning(plan):
        # The provider policy replaces every routing key, so removed_groups and
        # removed_rules count local entries the new source does not contain.
        # Approved contract; never downgrade or refuse behind the user's back.
        units = []
        for key, unit in (("removed_groups", "个本地分组"), ("removed_rules", "条本地规则")):
            value = plan.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                units.append("{} {}".format(value, unit))
        if not units:
            return
        print("警告：此预览会移除本地的" + "、".join(units) +
              "；提供商策略按订阅内容整体替换，请确认后再保存；不保留历史备份。")
    from mihomoctl.onboarding import needs_setup
    if needs_setup(getattr(service, 'app', None)):
        try:
            service.prepare()
            print("首次配置：选择 3 导入订阅，再选择 2 选择节点。")
        except (ControlError, OSError) as error:
            print("配置尚未就绪：" + getattr(error, 'code', 'config-unavailable'))
    print("使用代理：mihomoctl exec -- <命令>")
    if importlib.util.find_spec("textual") is None:
        print("更多功能：Textual 可用户私有安装：" + TUI_INSTALL_COMMAND)
    while True:
        if initial_preview:
            print("已收到标准输入订阅预览；选择 3 审阅并保存。")
        print("\nMihomo 管理\n1. 运行时状态  2. 选择节点  3. 导入订阅\n4. 初始化控制器  5. 启动  6. 停止  7. 重启生效\n8. 切换模式  10. 探测配置  11. 历史日志\n12. 代理档案与接入  q. 退出")
        choice = input("请选择: ").strip().lower()
        try:
            if choice == "q":
                return {"state": "closed", "shell": "unchanged"}
            if choice == "1":
                runtime = service.read("runtime")
                print("运行时（作用域 {}）".format(runtime.get("scope", "未知")))
                for key, title in (("core", "核心"), ("controller", "控制器"),
                                   ("listeners", "监听"), ("config", "生效配置"),
                                   ("proxy_mode", "代理模式"), ("routing_mode", "核心路由模式"), ("tun", "TUN"),
                                   ("error", "错误")):
                    print("  {}：{}".format(title, describe(runtime.get(key))))
                if runtime.get("reason"):
                    print("  原因：" + str(runtime["reason"]))
                value = service.read("overview")
                print("控制器: {}  核心: {}  模式: {}".format(value.get("controller"), value.get("core", "未知"), value.get("mode", "未知")))
                print("待重启: " + ("是" if value.get("pending_restart") else "否"))
                if value.get("error"):
                    print("尚未连接: " + value["error"] + "；可选 4 初始化，再选 7 重启或检查配置。")
                for group in value.get("groups", []):
                    print("{} → {}".format(group["name"], group.get("selected") or "自动"))
            elif choice == "2":
                plain_tui(service.client())
            elif choice == "3":
                if initial_preview:
                    plan, initial_preview = initial_preview, None
                else:
                    import getpass
                    kind = "file" if input("来源：1 订阅 URL / 2 YAML 文件 [1]: ").strip() == "2" else "url"
                    value = (getpass.getpass("HTTPS 订阅 URL（隐藏输入）: ") if kind == "url"
                             else input("YAML 文件路径: "))
                    plan = service.subscription_input(value.strip(), kind=kind, policy="simple")
                print("预览：策略 {}；节点 {}，分组 {}，规则 {}；移除节点 {}；忽略设置：{}".format(plan.get("policy", "provider"), plan.get("nodes", 0), plan.get("groups", 0), plan.get("rules", 0), plan.get("removed", 0), ", ".join(plan.get("ignored_fields", []))))
                clearing_warning(plan)
                if plan.get("probe_overwrites"):
                    print("订阅会覆盖现有探测设置：" + json.dumps(plan["probe_overwrites"], ensure_ascii=False))
                if confirm("保存订阅并启动或重启当前用户的代理？不保留历史备份。"):
                    service.subscription_save_and_start(plan["id"], plan["sha256"])
                    print("已保存并启动。选择 2 搜索、测速和选择节点。")
                elif getattr(service, 'subscription_discard', None):
                    service.subscription_discard(plan['id'])
            elif choice == "4" and confirm("创建本机控制器和随机密钥？"):
                result = service.initialize()
                print("配置状态：" + result["state"] + "；如有变更，请选择 7 重启。")
            elif choice in ("5", "6", "7"):
                action = {"5": "start", "6": "stop", "7": "restart"}[choice]
                if confirm("确认更改当前用户的代理服务？"):
                    result = service.lifecycle(action)
                    if result.get("overall") != "PASS":
                        print("未完成：" + str(result.get("reason", "运行时不可用")))
                    else:
                        print("操作已完成。")
            elif choice == "8":
                mode = {"1": "rule", "2": "global", "3": "direct"}.get(input("1 规则 / 2 全局 / 3 直连: ").strip())
                if mode:
                    service.mode(mode)
                    print("运行模式已切换。")
            elif choice == "10":
                print('必须以 group 或 provider 开头：group "组名" 或 provider "名称"；可加 --preset resilient 或 --url / --expected-status / --interval / --timeout / --lazy / --tolerance。')
                scope, name, options = parse_console(input("探测配置: "))
                result = service.health_check(scope, name, options)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if result.get("state") == "preview" and confirm("校验、保存探测设置？需单独重启。"):
                    service.health_check(apply=True)
                    print("已保存，请选择 7 重启。")
            elif choice == "11":
                since, until = input("开始时间（留空不限）: ").strip(), input("结束时间（留空不限）: ").strip()
                print(json.dumps(service.journal(since=since or None, until=until or None), ensure_ascii=False, indent=2))
            elif choice == "12":
                value = service.read("profile")
                if value.get("overall") not in (None, "PASS"):
                    print("代理档案暂不可用：" + str(value.get("reason", "未知")))
                    print("先完成 init；档案来自 manager.yaml，不需要控制器已启动。")
                else:
                    print("代理档案（作用域 {}）".format(value.get("scope", "未知")))
                    for row in value.get("profiles") or []:
                        print(" {} {} 监听={} 凭据={}".format(
                            "*" if row.get("selected") else " ", row.get("name"),
                            ", ".join(str(item) for item in (row.get("listeners") or [])) or "未声明",
                            row.get("credentials", "external")))
                    print("当前档案：" + str(value.get("selected") or "未选择"))
                    bindings = value.get("bindings") or {}
                    print("\n接入（仅导出配置，不管理第三方生命周期）")
                    if not bindings:
                        print("  尚无接入声明。")
                    for name, row in bindings.items():
                        row = row if isinstance(row, dict) else {}
                        print("  {} -> {} · {} · 目标 {}".format(
                            name, row.get("adapter", "未知"), row.get("profile", "default"),
                            row.get("target", "-")))
                    print("\n环境注入边界")
                    for limit in value.get("environment") or []:
                        print("  - " + str(limit))
        except (ControlError, files.InstallError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            print("操作未完成：" + error_text(getattr(error, "code", "配置或环境不可用"), getattr(error, "detail", "")))
            print("检查私有配置、订阅连通性与核心是否存在后重试。")


def release_notice_lines(notice, width):
    return [line for paragraph in notice.splitlines()
            for line in textwrap.wrap(paragraph, max(1, width - 2))]


def display_width(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def wrap_cells(text, width):
    lines, line = [], ""
    for char in text:
        if line and display_width(line + char) > max(1, width):
            lines.append(line)
            line = ""
        line += char
    return lines + ([line] if line else [])


def legend_lines(width):
    items = (("↑↓", "浏览"), ("Tab", "切面板"), ("Enter", "选择"), ("q", "退出"),
             ("/", "搜索"), ("r", "刷新"), ("t", "测速"), ("c", "连接"),
             ("f", "流量"), ("m", "手动"), ("o", "脚本"), ("y", "保存"))
    def pack(labels):
        rows = [""]
        for key, title in items:
            token = key + (" " + title if labels else "")
            candidate = (rows[-1] + "  " + token).strip()
            if display_width(candidate) > width:
                rows.append(token)
            else:
                rows[-1] = candidate
        return rows
    rows = pack(True)
    if len(rows) > 2:
        rows = pack(False)
    if len(rows) > 2 or any(display_width(row) > width for row in rows):
        # Preserve every key even when two rows cannot fit; put() clips safely.
        rows = [rows[0], "  ".join(rows[1:])]
    return (rows + [""])[:2]


def curses_header(width):
    full = "Nodes 节点 | /搜 Search c连 Conn o预览 Override m手动 Manual"
    compact = "Nodes节点 /搜Search c连Conn o预览Override m手动Manual"
    return full if display_width(full) <= width else compact


def plain_tui(client):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    from mihomoctl.notifications import take_tui_notice
    notice = take_tui_notice()
    if notice:
        print(notice)
    while True:
        client.verify()
        groups = list(snapshot(client, "groups")["groups"])
        print("\nMihomo · 策略组 / Groups (q: quit, Enter: refresh)")
        for i, group in enumerate(groups, 1):
            print("{}. {} [{}] → {}".format(i, group["name"], group["type"], group["selected"] or "dynamic"))
        answer = input("选择策略组 / Group: ").strip()
        if answer.lower() == "q":
            return {"state": "closed"}
        if not answer.isdigit() or not 1 <= int(answer) <= len(groups):
            continue
        group = groups[int(answer) - 1]
        for line in guidance(group):
            print(line)
        if not group["selectable"]:
            print("自动/负载均衡组只读；请选择 Selector。 / Automatic group is read-only.")
            continue
        for i, name in enumerate(group["members"], 1):
            print("{}. {}{}".format(i, name, " ✓" if name == group["selected"] else ""))
        answer = input("切换到 / Select (Enter: cancel): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(group["members"]):
            node = group["members"][int(answer) - 1]
            if input("确认将 {} 切换为 {}？共享入口影响见上方 [y/N]: ".format(group["name"], node)).strip().lower() == "y":
                select(client, group["name"], node)
                print("已确认切换；已有连接不强制断开。 / Selection confirmed; existing connections unchanged.")


def tui(client, plain=False, config=None, script=None, home_dir=None, details=False, flclash=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    if plain:
        return plain_tui(client)
    try:
        import curses
    except ImportError:
        raise ControlError("curses-unavailable-use-tui-plain") from None

    def screen(window):
        from mihomoctl.notifications import take_tui_notice
        release_notice = take_tui_notice()
        notice_until = time.monotonic() + 30
        curses.curs_set(0)
        window.keypad(True)
        window.timeout(1000)
        groups, group_index, node_index, focus = [], 0, 0, 0
        note, detail = "", []
        query, pending = "", None
        delays = {}
        last_refresh = 0
        def put(y, x, value, width, attr=0):
            # Curses counts terminal cells; avoid splitting wide node names.
            text, used = "", 0
            for char in value:
                size = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
                if used + size >= width:
                    break
                text += char; used += size
            try:
                window.addstr(y, x, text, attr)
            except curses.error:
                pass  # A resize may happen between getmaxyx and drawing.

        while True:
            if time.monotonic() - last_refresh >= 5:
                try:
                    previous_group = groups[group_index]["name"] if groups else None
                    previous_members = [name for name in groups[group_index].get("members", []) if query.casefold() in name.casefold()] if groups else []
                    previous_node = previous_members[node_index] if node_index < len(previous_members) else None
                    client.verify()
                    groups = snapshot(client, "groups")["groups"]
                    names = [row["name"] for row in groups]
                    group_index = names.index(previous_group) if previous_group in names else 0
                    members = [name for name in groups[group_index].get("members", []) if query.casefold() in name.casefold()] if groups else []
                    node_index = members.index(previous_node) if previous_node in members else 0
                    note = "已刷新 / Refreshed " + time.strftime("%H:%M:%S")
                except ControlError as error:
                    note = "UNVERIFIED: " + error_text(error.code, error.detail)
                last_refresh = time.monotonic()
            height, width = window.getmaxyx()
            window.erase()
            if height < 14 or width < 60:
                put(0, 0, "Terminal too small; resize to 60x14 or use tui --plain. q: quit", width)
                window.refresh()
                if window.getch() in (ord('q'), 27): return
                continue
            middle = min(max(26, width // 3), 42)
            group = groups[group_index] if groups else None
            members = [n for n in group.get("members", []) if query.casefold() in n.casefold()] if group else []
            node_index = min(node_index, max(0, len(members)-1))
            put(0, 1, "MIHOMO · 我的节点 / My nodes", width-2, curses.A_BOLD)
            put(1, 1, curses_header(width-3), width-2)
            put(2, 1, "组 Group: " + (group["name"] if group else "none") + " | " +
                ("MANUAL" if group and group["selectable"] else "AUTO / read-only") +
                " 筛选 Filter: " + (query or "all"), width-2, curses.A_BOLD)
            put(3, 1, "策略组 / Groups", middle-2, curses.A_BOLD)
            put(3, middle, "节点 / Nodes ({})  [*] selected".format(len(members)), width-middle-1, curses.A_BOLD)
            for y in range(3, height-6):
                put(y, middle-1, "│", 1, curses.A_DIM)
            available = max(1, height-11)
            start = max(0, group_index-available+1)
            for index in range(start, min(len(groups), start+available)):
                row = groups[index]
                put(4+index-start, 1, ("> " if index == group_index else "  ")+row["name"]+" ["+row["type"]+"]", middle-2,
                    curses.A_REVERSE if index == group_index and focus == 0 else curses.A_NORMAL)
            start = max(0, node_index-available+1)
            for index in range(start, min(len(members), start+available)):
                name = members[index]
                suffix = "  {} ms".format(delays[name]) if name in delays else ""
                put(4+index-start, middle, ("[*] " if group.get("selected") == name else "[ ] ")+name+suffix,
                    width-middle-1, curses.A_REVERSE if index == node_index and focus == 1 else curses.A_NORMAL)
            put(height-6, 1, "当前 / Current: " + (group.get("selected") or "dynamic") if group else "No groups", width-2)
            put(height-5, 1, note, width-2)
            for index, line in enumerate(detail[:2]):
                put(height-4+index, 1, line, width-2)
            for index, line in enumerate(legend_lines(width-3)):
                put(height-2+index, 1, line, width-2)
            if release_notice and time.monotonic() < notice_until:
                lines = release_notice_lines(release_notice, width)
                for row, line in enumerate(lines[-(height-5):]):
                    y = max(4, height - 2 - len(lines)) + row
                    put(y, 1, ' ' * (width-2), width-2)
                    put(y, 1, line, width-1)
            window.refresh()
            key = window.getch()
            if key != -1:
                release_notice = None
            if key in (ord('q'), 27): return
            if key == ord('/'):
                put(height-5, 1, "Search (empty clears): ", width-2); window.refresh()
                window.timeout(-1); curses.echo(); curses.curs_set(1)
                try:
                    query = window.getstr(height-5, 24, min(120, width-26)).decode("utf-8", errors="replace")
                finally:
                    curses.noecho(); curses.curs_set(0); window.timeout(1000)
                node_index = 0
                continue
            if key in (ord('m'), ord('o'), ord('y')):
                try:
                    if not config:
                        raise ControlError("policy-edit-requires-config")
                    if key == ord('y'):
                        if pending is None:
                            note = "Preview with m or o first."
                            continue
                        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
                            result = apply_policy(config, pending[0], pending[1], home_dir)
                        detail = ["No historical backup is retained.", "Exit; run mihomoctl restart when ready."]
                        note = "Saved; running policy unchanged until restart."
                        pending = None
                    else:
                        if key == ord('o') and not script:
                            note = "Start with tui --script /ABSOLUTE/trusted-override.js"
                            continue
                        if key == ord('m') and (not group or group["name"] == "GLOBAL"):
                            raise ControlError("choose-configured-policy-group")
                        pending = policy_candidate(config, script=script if key == ord('o') else None,
                                                   group=group["name"] if group else None, flclash=flclash,
                                                   home_dir=home_dir)
                        summary = pending[2]
                        note = "PREVIEW: " + ", ".join(summary["changed_sections"]) + " | y saves, q cancels"
                        detail = ["Groups: " + ", ".join(g["name"] for g in summary["groups"]),
                                  "规则 {}；保存后需重启".format(summary["rule_count"])]
                except (ControlError, files.InstallError, OSError, ValueError, subprocess.TimeoutExpired) as error:
                    pending = None
                    note = "FAIL: " + (error.code if isinstance(error, ControlError) else "policy-operation-failed")
                continue
            if key in (9, curses.KEY_LEFT, curses.KEY_RIGHT): focus = 1-focus
            elif key in (curses.KEY_UP, curses.KEY_DOWN):
                step = -1 if key == curses.KEY_UP else 1
                if focus == 0:
                    group_index = max(0, min(len(groups)-1, group_index+step)); node_index = 0
                else:
                    node_index = max(0, min(len(members)-1, node_index+step))
            elif key == ord('r'): last_refresh = 0
            elif key in (10, 13, curses.KEY_ENTER, ord('t'), ord('c'), ord('f')):
                if key in (10, 13, curses.KEY_ENTER) and focus == 0:
                    focus = 1
                    if group and group.get("selected") in members:
                        node_index = members.index(group["selected"])
                    continue
                try:
                    client.verify()
                    if key == ord('c'):
                        rows = snapshot(client, "connections", details)["connections"]
                        detail = [(row.get("host", "") + " | " if details else "") + " ← ".join(row["chains"]) for row in rows[:2]] or ["No active connections"]
                        note = "前两条链路；全部见 mihomoctl connections"
                    elif key == ord('f'):
                        values = snapshot(client, "traffic")
                        detail = ["↑ {} B/s   ↓ {} B/s".format(values["up"], values["down"])]
                    elif group and members:
                        if key == ord('t'):
                            name = members[node_index]
                            note = "Testing public HTTPS target..."; put(height-5, 1, note, width-2); window.refresh()
                            delays[name] = measure_delay(client, name)["delay_ms"]
                            detail = wrap_cells(name+": "+str(delays[name])+" ms; UNVERIFIED", width-3)[:2]
                        else:
                            if not group["selectable"]:
                                note = "自动组只读 / Auto group: m previews conversion to manual; y saves."
                                continue
                            select(client, group["name"], members[node_index])
                            groups = snapshot(client, "groups")["groups"]
                            note = "已确认切换 / Selection confirmed; existing connections unchanged"
                        last_refresh = time.monotonic()
                except ControlError as error:
                    detail = wrap_cells(error_text(error.code, error.detail), width-3)[:2]
                    note = "FAIL: " + error.code
    try:
        curses.wrapper(screen)
    except curses.error:
        raise ControlError("terminal-unavailable-use-tui-plain") from None
    return {"state": "closed"}
