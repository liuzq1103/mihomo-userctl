"""Optional frontend interaction tests using Textual's headless Pilot."""
import asyncio
import importlib.util
import sys
import unittest

if sys.platform != "linux" or importlib.util.find_spec("textual") is None:
    raise unittest.SkipTest("optional Textual test environment")

from mihomoctl.controller.controller_textual import clearing_warnings, preview_summary, report_lines, Console
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
    def subscription_input(self, value, kind='url', policy='simple'):
        return self.subscription_preview(value, url=kind=='url', policy=policy)
    def subscription_save_and_start(self, identifier, digest):
        self.subscription_apply(identifier, digest)
        self.shell('restart')
        return {'state': 'ready', 'action': 'restart', 'overall': 'PASS'}


class TextualTests(unittest.IsolatedAsyncioTestCase):
    def test_all_delay_identities_use_unambiguous_keys(self):
        from mihomoctl.controller.controller_textual import delay_key
        global_target={'provider':None,'name':'["p", "n"]'}
        provider_target={'provider':'p','name':'n'}
        self.assertNotEqual(delay_key(global_target),delay_key(provider_target))
        self.assertEqual(delay_key(global_target),delay_key(global_target['name']))
        values={delay_key(global_target):'失败：探测超时',delay_key(provider_target):37}
        self.assertEqual(len(values),2)
        from mihomoctl.controller.controller_types import node_identity
        target={'name':'https://example.test/PRIVATE-PASSWORD','provider':'p'}
        safe={'name':'[redacted request]','provider':'p','target_id':node_identity(target['name'],'p')}
        self.assertEqual(delay_key(target),delay_key(safe))
    def test_delay_codes_are_translated_in_results_and_hints(self):
        from mihomoctl.controller.controller_types import ERROR_LABELS, error_text
        from mihomoctl.controller.controller_textual import summarize
        for code in ('node-not-in-core', 'node-unreachable', 'delay-timeout'):
            rows = report_lines({'results': [{'name': 'A', 'state': 'failed', 'error': code}]})
            self.assertIn(ERROR_LABELS[code], '\n'.join(rows))
            self.assertIn(code, '\n'.join(rows))
            self.assertIn(ERROR_LABELS[code], summarize('error', code))
            self.assertIn(code, summarize('error', code))
        message = error_text('textual-environment-incomplete-use-engine-curses')
        self.assertIn('textual/rich', message)
        self.assertIn('mihomoctl tui --engine curses', message)
        self.assertIn('--extras tui', message)

    async def test_single_node_failure_keeps_code_label_in_store_and_hint(self):
        from mihomoctl.controller.controller_types import ControlError, ERROR_LABELS
        from textual.widgets import Static
        class Failed(Service):
            def latency(self, node):
                raise ControlError('delay-timeout')
        service = Failed()
        app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, 'overview')
            app.schedule('operation', lambda: service.latency('B'))
            await self.wait_for(pilot, lambda: app.store.state.snapshots.get('operation') and
                                app.store.state.snapshots['operation'].error, 'single node failure')
            await pilot.pause(.2)
            snapshot = app.store.state.snapshots['operation']
            self.assertEqual(snapshot.error, 'delay-timeout')
            self.assertEqual(snapshot.error_label, ERROR_LABELS['delay-timeout'])
            rendered = str(app.query_one('#hint', Static).render())
            self.assertIn('delay-timeout', rendered)
            self.assertIn(ERROR_LABELS['delay-timeout'], rendered)

    async def test_batch_failure_cancellation_and_progress_never_look_untested(self):
        import threading
        from textual.widgets import Static
        finished=threading.Event()
        class Mixed(Service):
            def batch_latency(self,targets,cancel,progress=None):
                finished.wait(5)
                return {'results':[{'name':'[red]A','state':'success','delay_ms':42},
                                   {'name':'B','state':'failed','error':'delay-timeout'},
                                   {'name':'q','state':'cancelled'}]}
        app=Console(Mixed())
        async with app.run_test(size=(120,28)) as pilot:
            app.change_page('proxies');await self.settle(pilot,app,'proxies')
            self.assertTrue(all(str(row[2])=='未测试' for row in [app.query_one('#nodes',DataTable).get_row_at(i) for i in range(3)]))
            from mihomoctl.controller.controller_textual import delay_key
            app.latencies[delay_key('B')]='123'  # A new failed attempt must replace stale success.
            app.start_batch(('[red]A','B','q'))
            self.assertEqual(app.latencies[delay_key('B')],'测速中')
            finished.set()
            await self.wait_for(pilot,lambda:'operation' not in app.store.pending,'batch results')
            await pilot.pause(.2)
            rows={str(row[0]):str(row[2]) for row in [app.query_one('#nodes',DataTable).get_row_at(i) for i in range(3)]}
            self.assertEqual(rows['[red]A'],'42')
            self.assertIn('超时',rows['B']);self.assertIn('delay-timeout',rows['B'])
            self.assertEqual(rows['q'],'已取消')
            hint=str(app.query_one('#hint',Static).render())
            self.assertIn('成功 1，失败 1，取消 1',hint)
            app.render_page()
            self.assertIn('成功 1，失败 1，取消 1',str(app.query_one('#hint',Static).render()))
            revision=app.store.state.snapshots['proxies'].revision
            app.action_refresh()
            await self.wait_for(pilot,lambda:app.store.state.snapshots['proxies'].revision>revision and 'proxies' not in app.store.pending,'fresh proxy snapshot')
            await pilot.pause(.2)
            self.assertIn('成功 1，失败 1，取消 1',str(app.query_one('#hint',Static).render()))
            rows={str(row[0]):str(row[2]) for row in [app.query_one('#nodes',DataTable).get_row_at(i) for i in range(3)]}
            self.assertIn('delay-timeout',rows['B']);self.assertEqual(rows['q'],'已取消')
            from mihomoctl.controller.controller_types import ControlError
            def activation_failure():
                error=ControlError('core-timeout')
                error.operation_state={'phase':'activate','config':'restored','runtime':'running','activation':'failed'}
                raise error
            app.schedule('operation',activation_failure)
            await self.wait_for(pilot,lambda:app.store.state.snapshots['operation'].error=='core-timeout','subsequent activation error')
            await pilot.pause(.2);app.render_page()
            notice=str(app.query_one('#hint',Static).render())
            self.assertIn('core-timeout',notice)
            self.assertIn('已恢复原配置',notice)
            self.assertNotIn('成功 1，失败 1，取消 1',notice)

    async def test_health_preview_requires_confirmed_save_and_journal_filters(self):
        class Tasks(Service):
            def health_check(self, scope=None, name=None, options=None, apply=False):
                self.calls.append(("health", scope, name, options, apply))
                if apply:
                    self.pending_restart = True
                    return {"state": "restart-required"}
                return {"state": "preview", "kind": "health-check", "scope": scope, "name": name,
                        "before": {"interval": 600}, "after": {"interval": 120}, "affected_groups": ["Work"]}
            def journal(self, **filters):
                self.calls.append(("journal", filters))
                return {"state": "no-records-in-window", "entries": []}
        service = Tasks(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            app.execute_command('health-check group "Shared Auto" --preset resilient')
            await self.wait_for(pilot, lambda: app.preview is not None, "health preview")
            self.assertEqual(service.calls[0], ("health", "group", "Shared Auto", {"preset": "resilient"}, False))
            app.action_save()
            await pilot.pause()
            self.assertEqual(len(service.calls), 1)
            await pilot.click("#yes")
            await self.wait_for(pilot, lambda: app.pending_restart, "health saved")
            self.assertTrue(service.calls[-1][-1])
            app.execute_command('journal --since "2026-10-10 21:09" --until "2026-10-10 21:14"')
            await self.wait_for(pilot, lambda: service.calls[-1][0] == "journal", "journal filters")
            self.assertEqual(service.calls[-1][1], {"since": "2026-10-10 21:09", "until": "2026-10-10 21:14"})
            count = len(service.calls)
            app.execute_command('health-check group Auto --apply')
            await pilot.pause()
            self.assertEqual(len(service.calls), count)

    async def test_auto_stdin_preview_keeps_requested_mode_after_mount(self):
        preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                   "requested_policy": "auto", "policy": "provider", "nodes": 1, "groups": 1, "rules": 1}
        app = Console(Service(), initial_preview=preview)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self.assertEqual(app.source_policy, "auto")
            self.assertIs(app.preview, preview)

    async def test_stdin_preview_opens_subscription_page_and_survives_mount_events(self):
        preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                   "policy": "provider", "nodes": 1, "groups": 1, "rules": 1}
        app = Console(Service(), initial_preview=preview)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "subscriptions")
            self.assertEqual(app.page, "subscriptions")
            self.assertEqual(app.preview, preview)
            app.action_save()
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 2)
            await pilot.press("escape")

    async def test_preview_success_save_failure_shows_phase_and_recovered_state(self):
        from mihomoctl.controller.controller_types import ControlError
        class FailedSave(Service):
            def subscription_save_and_start(self, identifier, digest):
                error = ControlError('core-timeout')
                error.safe_detail = 'stage=core-validation; elapsed_ms=60000; cache_files=1'
                error.operation_state = {'phase':'activate','config':'restored','runtime':'running','activation':'failed'}
                raise error
        preview = {'state':'preview','id':'a'*32,'sha256':'b'*64,'policy':'policy','nodes':0,'groups':1,'rules':1}
        app = Console(FailedSave(), initial_preview=preview)
        async with app.run_test(size=(100,28)) as pilot:
            await pilot.pause()
            app.action_save(); await pilot.pause(); await pilot.click('#yes')
            await self.wait_for(pilot, lambda: bool(app.store.state.snapshots['operation'].error), 'save failure observed')
            snap=app.store.state.snapshots['operation']
            self.assertEqual(snap.error,'core-timeout')
            self.assertIn('已恢复原配置，新配置未提交',snap.error_message)
            self.assertIn('仍在运行',snap.error_message)
            self.assertIn('启动或重启',snap.error_message)
            self.assertNotEqual(app.page,'proxies')

    async def test_provider_row_identity_survives_single_and_batch_latency(self):
        class Providers(Service):
            def read(self,page):
                if page=='proxies':
                    return {'Proxy':{'name':'Proxy','type':'Selector','members':['duplicate'],'selected':'duplicate','selectable':True,
                                     'member_targets':[{'name':'duplicate','provider':'first'},{'name':'duplicate','provider':'second'}]}}
                return super().read(page)
            def latency(self,target):
                self.calls.append(('latency',target))
                return dict(target,delay_ms=32)
            def batch_latency(self,targets,cancel,progress=None):
                self.calls.append(('batch',targets))
                return {'results':[dict(t,delay_ms=32) for t in targets]}
        service=Providers();app=Console(service)
        async with app.run_test(size=(100,28)) as pilot:
            app.change_page('proxies');await self.settle(pilot,app,'proxies')
            app.query_one('#nodes',DataTable).move_cursor(row=1)
            app.action_latency()
            await self.wait_for(pilot,lambda:any(c[0]=='latency' for c in service.calls),'provider single target')
            self.assertIn(('latency',{'name':'duplicate','provider':'second'}),service.calls)
            app.action_batch();await pilot.pause();await pilot.click('#yes')
            await self.wait_for(pilot,lambda:any(c[0]=='batch' for c in service.calls),'provider batch targets')
            targets=next(c[1] for c in service.calls if c[0]=='batch')
            self.assertEqual({t['provider'] for t in targets},{'first','second'})
            app.query_one('#nodes',DataTable).focus();await pilot.press('enter');await pilot.pause()
            self.assertFalse(any(c[0]=='select' for c in service.calls))

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
                await self.settle(pilot, app, "subscriptions")
                app.query_one("#source-kind", Select).value = "file"
                await pilot.pause()
                app.query_one("#source-path", Input).value = "/private/provider.yaml"
                await pilot.pause()
                self.assertGreaterEqual(app.query_one("#body", RichLog).region.height, 2)
                await pilot.click("#subscription-preview")
                await self.settle(pilot, app, "operation")
                self.assertEqual(service.calls, [("preview", "/private/provider.yaml", False, "simple")])
                self.assertEqual(app.preview["groups"], 2)
                await pilot.click("#subscription-save")
                await pilot.pause()
                self.assertEqual(len(service.calls), 1)
                await pilot.click("#yes")
                await self.wait_for(pilot, lambda: app.page == 'proxies', 'saved subscription opens nodes')
                self.assertFalse(app.pending_restart)
                self.assertEqual(service.calls[-1], ('service', 'restart'))
                self.assertEqual(len(app.query('#restore-backup')), 0)
                self.assertEqual(app.query_one('#source-path', Input).value, '')

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

    async def test_policy_selector_defaults_to_auto_and_keeps_explicit_nodes(self):
        class Tasks(Service):
            def subscription_preview(self, path, url=False, policy="provider"):
                self.calls.append(("preview", path, url, policy))
                return {"state": "preview", "id": "a"*32, "sha256": "b"*64, "policy": policy,
                        "nodes": 1, "groups": 1, "rules": 1, "ignored_fields": []}
        service = Tasks(); app = Console(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#nav-profiles")
            await self.settle(pilot, app, "subscriptions")
            self.assertEqual(app.source_policy, "simple")
            self.assertEqual(app.query_one("#source-policy", Select).value, "simple")
            app.query_one('#source-kind', Select).value = 'file'
            await pilot.pause()
            app.query_one("#source-path", Input).value = "/private/nodes.yaml"
            await pilot.pause()
            await pilot.click("#subscription-preview")
            # A worker records its call before Store publishes the result and
            # Console.tick applies it. Wait for that UI completion before
            # reading the preview or changing the selectors for the next one.
            await self.wait_for(pilot, lambda: app.preview is not None, "provider preview published")
            self.assertEqual(service.calls, [("preview", "/private/nodes.yaml", False, "simple")])
            self.assertEqual(app.preview["policy"], "simple")
            self.assertFalse(app.query_one("#source-policy", Select).disabled)
            # Switching the policy invalidates the review; it never downgrades it.
            app.query_one("#source-policy", Select).value = "nodes"
            await pilot.pause()
            self.assertEqual(app.source_policy, "nodes")
            self.assertIsNone(app.preview)
            # Textual suppresses clicks while the previous press animation is
            # active, even after the worker result has been published. Wait for
            # the actual button to accept input before requesting another review.
            await self.wait_for(pilot, lambda: not app.query_one("#subscription-preview").has_class("-active"),
                                "preview button ready after policy change")
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: app.preview is not None, "nodes preview published")
            self.assertEqual(len(service.calls), 2)
            self.assertEqual(service.calls[1], ("preview", "/private/nodes.yaml", False, "nodes"))
            self.assertEqual(app.preview["policy"], "nodes")
            app.query_one("#source-kind", Select).value = "url"
            await pilot.pause()
            self.assertIsNone(app.preview)
            app.query_one('#source-path', Input).value = 'https://example.invalid/subscription'
            await pilot.pause()
            await self.wait_for(pilot, lambda: not app.query_one("#subscription-preview").has_class("-active"),
                                "preview button ready after source change")
            await pilot.click("#subscription-preview")
            await self.wait_for(pilot, lambda: app.preview is not None, "url preview published")
            self.assertEqual(len(service.calls), 3)
            self.assertEqual(service.calls[2], ("preview", "https://example.invalid/subscription", True, "nodes"))
            self.assertEqual(app.preview["policy"], "nodes")

    async def test_piped_nodes_policy_seeds_the_selector_and_keeps_the_review(self):
        for policy in ("provider", "nodes"):
            preview = {"state": "preview", "id": "a"*32, "sha256": "b"*64,
                       "policy": policy, "nodes": 1, "groups": 1, "rules": 1}
            app = Console(Service(), initial_preview=preview)
            async with app.run_test(size=(80, 24)) as pilot:
                await self.settle(pilot, app, "subscriptions")
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
            await self.settle(pilot, app, "subscriptions")
            app.query_one("#source-kind", Select).value = "file"
            await pilot.pause()
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
            self.assertEqual(service.calls, [("preview", "/private/provider.yaml", False, "simple")])

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
            await self.settle(pilot, app, "subscriptions")
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
            for page in ("overview", "connections", "rules", "logs", "subscriptions",
                         "profile", "providers", "diagnostics", "runtime"):
                app.query_one("#navigation", Select).value = page
                await self.settle(pilot, app, page)
            app.query_one("#navigation", Select).value = "connections"
            await pilot.pause()
            app.action_pause()
            self.assertTrue(app.paused)
            app.action_pause()
            self.assertFalse(app.paused)
            self.assertEqual(app.theme, "textual-light")

    async def test_retained_profiles_identifier_still_routes_to_subscriptions(self):
        """The old page name is a compatibility alias, not a second page."""
        app = Console(Service())
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(pilot, app, "overview")
            app.change_page("profiles")
            await pilot.pause()
            self.assertEqual(app.page, "subscriptions")
            # One subscription, two identifiers: the snapshot object is shared,
            # so the alias never drifts from the canonical page.
            canonical = app.store.state.snapshots["subscriptions"]
            self.assertIs(app.store.state.snapshots["profiles"], canonical)
            # The nav button keeps its retained widget id and opens the same page.
            await pilot.click("#nav-profiles")
            await self.settle(pilot, app, "subscriptions")
            self.assertEqual(app.page, "subscriptions")
            # The profile page is a genuinely different destination.
            app.change_page("profile")
            await self.settle(pilot, app, "profile")
            self.assertEqual(app.page, "profile")
            self.assertIsNot(app.store.state.snapshots["profile"],
                              app.store.state.snapshots["subscriptions"])
