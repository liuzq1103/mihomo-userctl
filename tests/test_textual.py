"""Optional frontend interaction tests using Textual's headless Pilot."""
import asyncio
import importlib.util
import sys
import unittest

if sys.platform != "linux" or importlib.util.find_spec("textual") is None:
    raise unittest.SkipTest("optional Textual test environment")

from scripts.controller_textual import clearing_warnings, preview_summary, report_lines, Console
from textual.widgets import DataTable, Input, Select, RichLog


class Service:
    details, script = False, None
    def __init__(self):
        self.calls = []
        # ConsoleService mirrors its private receipt here; the console may only
        # read these, never keep a second copy that drifts.
        self.pending_restart, self.backup = False, None
    def read(self, page):
        if page == "proxies":
            return {"Proxy": {"name": "Proxy", "type": "Selector", "members": ["[red]A", "B", "q"], "selected": "B", "selectable": True},
                    "Auto": {"name": "Auto", "type": "URLTest", "members": ["B"], "selected": "B", "selectable": False}}
        if page == "connections":
            return {"connections": [{"chains": ["B", "Proxy"], "rule": "Match", "upload": 1, "download": 2}]}
        if page == "rules":
            return {"types": {"Match": 1}}
        if page == "providers":
            return {"providers": [{"name": "nodes", "type": "HTTP", "nodes": 2, "updated": "now"}]}
        if page == "logs":
            return {"level": "info", "message": "private log entry"}
        if page == "traffic":
            return {"up": 1, "down": 2}
        if page == "memory":
            return {"inuse": 1024, "oslimit": 0}
        return {"service": "active", "authentication": "UNVERIFIED"}
    def choose(self, group, node):
        self.calls.append(("select", group, node))
        return {"state": "confirmed"}
    def batch_latency(self, nodes, cancel, progress=None):
        self.calls.append(("batch", tuple(nodes)))
        return {"results": [{"name": n, "delay_ms": 32} for n in nodes]}
    def latency(self, node):
        return {"name": node, "delay_ms": 32}


class TextualTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdin_preview_opens_subscription_page_and_survives_mount_events(self):
        preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                   "policy": "provider", "nodes": 1, "groups": 1, "rules": 1}
        app = Console(Service(), initial_preview=preview)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "profiles")
            self.assertEqual(app.page, "profiles")
            self.assertEqual(app.preview, preview)
            app.action_save()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 2)
            await pilot.press("escape")

    async def test_subscription_buttons_preview_save_restart_and_compact_fit(self):
        class Tasks(Service):
            def subscription_preview(self, path, url=False, policy="provider"):
                self.calls.append(("preview", path, url, policy))
                return {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                        "policy": policy, "nodes": 2, "groups": 2, "rules": 1,
                        "ignored_fields": ["secret"]}
            def subscription_apply(self, identifier, digest):
                self.calls.append(("save", identifier, digest))
                self.pending_restart, self.backup = True, "/private/config.before-policy-fixture"
                return {"state": "restart-required", "backup": self.backup}
            def shell(self, action):
                self.calls.append(("service", action))
                if action in ("start", "restart"):
                    self.pending_restart = False
                return {"state": "confirmed", "action": action}
        for size in ((80, 24), (60, 14)):
            service = Tasks(); app = Console(service)
            async with app.run_test(size=size) as pilot:
                await pilot.click("#nav-profiles")
                await self.settle(pilot, app, "profiles")
                app.query_one("#source-path", Input).value = "/private/provider.yaml"
                await pilot.pause()
                self.assertGreaterEqual(app.query_one("#body", RichLog).region.height, 2)
                await pilot.click("#subscription-preview")
                await self.settle(pilot, app, "operation")
                self.assertEqual(service.calls, [("preview", "/private/provider.yaml", False, "provider")])
                self.assertEqual(app.preview["groups"], 2)
                await pilot.click("#subscription-save")
                await pilot.pause()
                self.assertEqual(len(service.calls), 1)
                await pilot.click("#yes")
                for _ in range(100):
                    if app.pending_restart: break
                    await pilot.pause(.02)
                self.assertTrue(app.pending_restart)
                self.assertTrue(app.query_one("#restore-backup").display)
                await pilot.click("#service-restart")
                await pilot.pause()
                await pilot.click("#yes")
                for _ in range(100):
                    if not app.pending_restart: break
                    await pilot.pause(.02)
                self.assertFalse(app.pending_restart)
                self.assertEqual(service.calls[-1], ("service", "restart"))
                # M1: the receipt is gone, so recovery must disappear with it.
                await pilot.pause()
                self.assertIsNone(app.last_backup)
                self.assertFalse(app.query_one("#restore-backup").display)

    async def test_missing_controller_home_offers_setup_and_automatic_group_is_read_only(self):
        class Missing(Service):
            def read(self, page):
                if page == "overview":
                    return {"controller": "unavailable", "error": "controller-not-configured-as-loopback", "groups": []}
                return super().read(page)
            def initialize(self):
                self.calls.append(("initialize",))
                self.pending_restart, self.backup = True, "/private/config.before-policy-fixture"
                return {"state": "restart-required", "backup": self.backup}
        service = Missing(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "overview")
            await pilot.click("#setup-controller")
            await pilot.pause()
            self.assertEqual(service.calls, [])
            await pilot.click("#yes")
            await self.settle(pilot, app, "operation")
            self.assertEqual(service.calls, [("initialize",)])
            await pilot.click("#nav-proxies")
            await self.settle(pilot, app, "proxies")
            app.group = "Auto"; app.render_page()
            app.query_one("#nodes", DataTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(service.calls, [("initialize",)])
            self.assertEqual(len(app.screen_stack), 1)

    async def test_policy_selector_defaults_to_provider_and_keeps_explicit_nodes(self):
        class Tasks(Service):
            def subscription_preview(self, path, url=False, policy="provider"):
                self.calls.append(("preview", path, url, policy))
                return {"state": "preview", "id": "a"*32, "sha256": "b"*64, "policy": policy,
                        "nodes": 1, "groups": 1, "rules": 1, "ignored_fields": []}
        service = Tasks(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#nav-profiles")
            await self.settle(pilot, app, "profiles")
            self.assertEqual(app.source_policy, "provider")
            self.assertEqual(app.query_one("#source-policy", Select).value, "provider")
            app.query_one("#source-path", Input).value = "/private/nodes.yaml"
            await pilot.pause()
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: len(service.calls) == 1, "provider preview")
            self.assertEqual(service.calls[0], ("preview", "/private/nodes.yaml", False, "provider"))
            # Switching the policy invalidates the review; it never downgrades it.
            app.query_one("#source-policy", Select).value = "nodes"
            await pilot.pause()
            self.assertEqual(app.source_policy, "nodes")
            self.assertIsNone(app.preview)
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: len(service.calls) == 2, "nodes preview")
            self.assertEqual(service.calls[1], ("preview", "/private/nodes.yaml", False, "nodes"))
            self.assertEqual(app.preview["policy"], "nodes")
            app.query_one("#source-kind", Select).value = "url"
            await pilot.pause()
            self.assertIsNone(app.preview)
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: len(service.calls) == 3, "url preview")
            self.assertEqual(service.calls[2], ("preview", "/private/nodes.yaml", True, "nodes"))

    async def test_piped_nodes_policy_seeds_the_selector_and_keeps_the_review(self):
        for policy in ("provider", "nodes"):
            preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                       "policy": policy, "nodes": 1, "groups": 1, "rules": 1}
            app = Console(Service(), initial_preview=preview)
            async with app.run_test(size=(80, 24)) as pilot:
                await self.settle(pilot, app, "profiles")
                # The mount-time Select.Changed must not discard the piped review.
                for _ in range(10):
                    await pilot.pause()
                self.assertEqual(app.source_policy, policy)
                self.assertEqual(app.query_one("#source-policy", Select).value, policy)
                self.assertIs(app.preview, preview)
                app.action_save()
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 2)
                await pilot.press("escape")

    async def test_provider_preview_reports_cleared_groups_and_rules(self):
        class Tasks(Service):
            def subscription_preview(self, path, url=False, policy="provider"):
                self.calls.append(("preview", path, url, policy))
                return {"state": "preview", "id": "a"*32, "sha256": "b"*64, "policy": policy,
                        "nodes": 3, "added": 1, "replaced": 2, "removed": 2, "groups": 1,
                        "rules": 2, "removed_groups": 4, "removed_rules": 57,
                        "ignored_fields": ["dns", "mixed-port"]}
        service = Tasks(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#nav-profiles")
            await self.settle(pilot, app, "profiles")
            app.query_one("#source-path", Input).value = "/private/provider.yaml"
            await pilot.pause()
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: app.preview is not None, "preview")
            summary = preview_summary(app.preview)
            self.assertIn("预览（尚未保存）", summary[0])
            self.assertIn("节点 3（新增 1、替换 2、移除 2）", summary[1])
            self.assertIn("分组 1（移除 4）", summary[1])
            self.assertIn("规则 2（移除 57）", summary[1])
            warning = "\n".join(clearing_warnings(app.preview))
            self.assertIn("4 个本地分组", warning)
            self.assertIn("57 条本地规则", warning)
            self.assertIn("不自动降级", warning)
            await pilot.click("#subscription-save")
            await pilot.pause()
            self.assertIn("4 个本地分组", app.screen_stack[-1].message)
            self.assertEqual(app.screen_stack[-1].accept, "确认")
            self.assertIn("57 条本地规则", app.screen_stack[-1].message)
            await pilot.press("escape")
            self.assertEqual(service.calls, [("preview", "/private/provider.yaml", False, "provider")])

    async def test_more_button_blanks_navigation_so_the_current_page_is_repickable(self):
        app = Console(Service())
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "overview")
            navigation = app.query_one("#navigation", Select)
            await pilot.click("#nav-more")
            await pilot.pause()
            self.assertTrue(navigation.display)
            self.assertEqual(navigation.value, Select.NULL)
            navigation.value = "overview"
            await pilot.pause()
            self.assertEqual(app.page, "overview")
            self.assertFalse(navigation.display)

    async def test_escape_cancels_a_seeded_preview_and_its_result(self):
        preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                   "policy": "provider", "nodes": 1, "groups": 1, "rules": 1}
        app = Console(Service(), initial_preview=preview)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "profiles")
            self.assertIs(app.preview, preview)
            app.action_cancel()
            await pilot.pause()
            self.assertIsNone(app.preview)
            self.assertNotIn("operation", app.store.state.snapshots)
            app.action_result()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 1)
            app.action_save()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 1)

    def test_report_lines_translates_status_keys_and_keeps_user_names(self):
        rows = report_lines({"state": "preview", "policy": "nodes", "service": "unchanged",
                             "action": "confirmed",
                             "changes": [{"name": "unchanged", "type": "ss", "action": "add"},
                                         {"name": "confirmed", "type": "ss", "action": "replace"}]})
        self.assertIn("状态: 预览（尚未保存）", rows)
        self.assertIn("导入策略: 仅合并节点", rows)
        self.assertIn("服务: 未改变", rows)
        self.assertIn("操作: 已完成", rows)
        # Nested entries are indented, so match by content rather than equality.
        self.assertTrue(any(line.endswith("名称: unchanged") for line in rows), rows)
        self.assertTrue(any(line.endswith("名称: confirmed") for line in rows), rows)
        self.assertTrue(any(line.endswith("操作: 新增") for line in rows), rows)
        self.assertTrue(any(line.endswith("操作: 替换") for line in rows), rows)
        # A count is never suppressed by a policy label, and never invented either.
        self.assertEqual(clearing_warnings({"policy": "nodes"}), [])
        self.assertEqual(clearing_warnings({"policy": "nodes", "removed_groups": 0}), [])
        self.assertTrue(clearing_warnings({"policy": "nodes", "removed_groups": 2}))
        self.assertEqual(clearing_warnings({}), [])
        summary = preview_summary({"state": "preview", "policy": "provider"})
        self.assertEqual(len(summary), 2)
        self.assertIn("状态 预览（尚未保存）", summary[0])
        self.assertIn("节点 0", summary[1])

    async def settle(self, pilot, app, page):
        for _ in range(100):
            snap = app.store.state.snapshots.get(page)
            if snap and snap.value is not None:
                await pilot.pause(.15)
                return
            await asyncio.sleep(.02)
        self.fail("page did not load: " + page)

    async def wait_for(self, pilot, predicate, description):
        for _ in range(200):
            if predicate():
                return
            await pilot.pause(.02)
        self.fail("condition not reached: " + description)

    async def test_search_markup_safe_select_requires_confirmation_and_keeps_focus(self):
        service = Service(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            app.query_one("#navigation", Select).value = "proxies"
            await self.settle(pilot, app, "proxies")
            nodes = app.query_one("#nodes", DataTable)
            self.assertEqual(nodes.get_row_at(0)[0].plain, "[red]A")
            nodes.focus()
            await pilot.press("/", "q")
            self.assertEqual(app.query_one("#search", Input).value, "q")
            self.assertEqual(app.visible_nodes, ["q"])
            await pilot.press("enter", "enter")
            await pilot.pause()
            self.assertEqual(service.calls, [])
            await pilot.click("#yes")
            await self.settle(pilot, app, "operation")
            self.assertEqual(service.calls, [("select", "Proxy", "q")])
            self.assertEqual(app.filter_text, "q")

    async def test_batch_targets_fixed_after_search_and_cancel_does_not_execute(self):
        service = Service(); app = Console(service)
        async with app.run_test(size=(100, 32)) as pilot:
            app.query_one("#navigation", Select).value = "proxies"
            await self.settle(pilot, app, "proxies")
            app.filter_text = "B"; app.render_page()
            app.action_batch(); await pilot.pause()
            await pilot.press("escape")
            self.assertEqual(service.calls, [])
            app.action_batch(); await pilot.pause()
            await pilot.click("#yes")
            await self.settle(pilot, app, "operation")
            self.assertEqual(service.calls, [("batch", ("B",))])

    async def test_all_pages_and_compact_layout_and_pause(self):
        app = Console(Service(), ascii_only=True, theme="light")
        async with app.run_test(size=(60, 14)) as pilot:
            for page in ("overview", "connections", "rules", "logs", "profiles", "providers", "diagnostics", "runtime"):
                app.query_one("#navigation", Select).value = page
                await self.settle(pilot, app, page)
            app.query_one("#navigation", Select).value = "connections"
            await pilot.pause()
            app.action_pause()
            self.assertTrue(app.paused)
            app.action_pause()
            self.assertFalse(app.paused)
            self.assertEqual(app.theme, "textual-light")
