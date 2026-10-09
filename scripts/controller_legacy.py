"""User-level controller component; no global proxy or daemon."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unicodedata
from urllib.parse import quote, urlencode
try:
    from . import install_support as files
except ImportError:
    import install_support as files
try:
    from .controller_types import ControlError, TEST_URL, number
    from .controller_service import select, snapshot
    from .controller_policy import policy_candidate
    from .controller_transaction import apply_policy
except ImportError:
    from controller_types import ControlError, TEST_URL, number
    from controller_service import select, snapshot
    from controller_policy import policy_candidate
    from controller_transaction import apply_policy

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
              "；提供商策略按订阅内容整体替换，不自动降级，可用 9 恢复备份回退。")
    while True:
        if initial_preview:
            print("已收到标准输入订阅预览；选择 3 审阅并保存。")
        print("\nMihomo 管理\n1. 首页状态  2. 选择节点  3. 导入订阅\n4. 初始化控制器  5. 启动  6. 停止  7. 重启生效\n8. 切换模式  9. 恢复备份  q. 退出")
        choice = input("请选择: ").strip().lower()
        try:
            if choice == "q":
                return {"state": "closed", "shell": "unchanged"}
            if choice == "1":
                try:
                    runtime = service.read("runtime")
                    print("服务状态：" + str(runtime.get("service", "未知")))
                except (ControlError, OSError, ValueError, TypeError):
                    print("服务状态：暂无法观测，可检查当前用户的 systemd 服务。")
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
                    policy = "nodes" if input("导入策略：1 提供商（节点/分组/规则整体替换） 2 仅合并节点 [1]: ").strip() == "2" else "provider"
                    url = input("来源类型：1 YAML 文件 / 2 私有 URL 文件 [1]: ").strip() == "2"
                    path = input("私有文件路径（请勿输入订阅 URL）: ").strip()
                    plan = service.subscription_preview(path, url=url, policy=policy)
                print("预览：策略 {}；节点 {}，分组 {}，规则 {}；移除节点 {}；忽略设置：{}".format(plan.get("policy", "provider"), plan.get("nodes", 0), plan.get("groups", 0), plan.get("rules", 0), plan.get("removed", 0), ", ".join(plan.get("ignored_fields", []))))
                clearing_warning(plan)
                if confirm("备份并保存此订阅策略？"):
                    service.subscription_apply(plan["id"], plan["sha256"])
                    print("已保存，尚未生效。选择 7 重启生效，或 9 恢复备份。")
            elif choice == "4" and confirm("创建本机控制器和随机密钥？"):
                result = service.initialize()
                print("配置状态：" + result["state"] + "；如有变更，请选择 7 重启。")
            elif choice in ("5", "6", "7"):
                action = {"5": "start", "6": "stop", "7": "restart"}[choice]
                if confirm("确认更改当前用户的代理服务？"):
                    service.shell(action)
                    print("操作已完成。")
            elif choice == "8":
                mode = {"1": "rule", "2": "global", "3": "direct"}.get(input("1 规则 / 2 全局 / 3 直连: ").strip())
                if mode:
                    service.mode(mode)
                    print("运行模式已切换。")
            elif choice == "9" and confirm("恢复本次操作前的配置？保存后仍需重启。"):
                service.restore()
                print("已恢复，请选择 7 重启。")
        except (ControlError, files.InstallError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            print("操作未完成：" + getattr(error, "code", "配置或环境不可用"))
            print("检查私有配置与核心是否存在；重启失败可选 9 恢复备份。")


def plain_tui(client):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
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
        if not group["selectable"]:
            print("自动/负载均衡组只读；请选择 Selector。 / Automatic group is read-only.")
            continue
        for i, name in enumerate(group["members"], 1):
            print("{}. {}{}".format(i, name, " ✓" if name == group["selected"] else ""))
        answer = input("切换到 / Select (Enter: cancel): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(group["members"]):
            select(client, group["name"], group["members"][int(answer) - 1])
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
                    note = "UNVERIFIED: " + error.code
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
            put(1, 1, "Nodes | / Search | c Connections | o Override | m Manual group", width-2)
            put(2, 1, "Group: " + (group["name"] if group else "none") + " | " +
                ("MANUAL" if group and group["selectable"] else "AUTO / read-only") +
                " | Filter: " + (query or "all"), width-2, curses.A_BOLD)
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
            put(height-2, 1, "↑↓ browse Tab pane Enter select / search m manual o script y apply r refresh t test q quit", width-2)
            window.refresh()
            key = window.getch()
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
                        detail = ["Backup: " + result.get("backup", "none"), "Exit; run mihomoctl restart when ready."]
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
                                  "Rules: {} | existing connections unchanged; restart required".format(summary["rule_count"])]
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
                        note = "Active chains (first 2); use mihomoctl connections for all."
                    elif key == ord('f'):
                        values = snapshot(client, "traffic")
                        detail = ["↑ {} B/s   ↓ {} B/s".format(values["up"], values["down"])]
                    elif group and members:
                        if key == ord('t'):
                            name = members[node_index]
                            note = "Testing public HTTPS target..."; put(height-5, 1, note, width-2); window.refresh()
                            raw = client.request("/proxies/"+quote(name, safe="")+"/delay?"+urlencode({"url": TEST_URL,"timeout":5000}))
                            delays[name] = number(raw.get("delay"))
                            detail = [name+": "+str(delays[name])+" ms; model UNVERIFIED"]
                        else:
                            if not group["selectable"]:
                                note = "自动组只读 / Auto group: m previews conversion to manual; y saves."
                                continue
                            select(client, group["name"], members[node_index])
                            groups = snapshot(client, "groups")["groups"]
                            note = "已确认切换 / Selection confirmed; existing connections unchanged"
                        last_refresh = time.monotonic()
                except ControlError as error:
                    note = "FAIL: " + error.code
    try:
        curses.wrapper(screen)
    except curses.error:
        raise ControlError("terminal-unavailable-use-tui-plain") from None
    return {"state": "closed"}
