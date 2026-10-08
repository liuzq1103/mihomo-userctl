"""Optional frontend interaction tests using Textual's headless Pilot."""
import asyncio
import importlib.util
import sys
import unittest

if sys.platform != "linux" or importlib.util.find_spec("textual") is None:
    raise unittest.SkipTest("optional Textual test environment")

from scripts.controller_textual import Console
from textual.widgets import DataTable, Input, Select


class Service:
    details, script = False, None
    def __init__(self):
        self.calls = []
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
    async def settle(self, pilot, app, page):
        for _ in range(100):
            snap = app.store.state.snapshots.get(page)
            if snap and snap.value is not None:
                await pilot.pause(.15)
                return
            await asyncio.sleep(.02)
        self.fail("page did not load: " + page)

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
