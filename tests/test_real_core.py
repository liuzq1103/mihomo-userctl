"""Opt-in real Mihomo integration; never installs a service or uses root."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

CORE = os.environ.get("MIHOMO_TEST_CORE")
if sys.platform != "linux" or not CORE:
    raise unittest.SkipTest("set MIHOMO_TEST_CORE to an explicitly prepared test binary")

from scripts.controller_service import ConsoleService
from scripts.controller_subscriptions import Subscriptions
from scripts import controller_runtime as runtime


class RealCoreTests(unittest.TestCase):
    def test_initialize_and_provider_policy_validate_with_real_core(self):
        from scripts.controller_dashboard import initialize
        from scripts.controller_config import read_config, endpoint
        with tempfile.TemporaryDirectory(prefix="muc-real-policy-") as folder:
            root = Path(folder)
            config, source = root / "config.yaml", root / "provider.yaml"
            config.write_text('mixed-port: 25000\nbind-address: 127.0.0.1\nallow-lan: false\nmode: rule\ngeo-auto-update: false\nproxies: []\nproxy-groups: [{name: Old, type: select, proxies: [DIRECT]}]\nrules: ["MATCH,Old"]\n')
            config.write_text(config.read_text() + 'listeners: null\n')
            config.chmod(0o600)
            (root / "providers").mkdir(mode=0o700)
            (root / "rules").mkdir(mode=0o700)
            nodes = root / "providers/local.yaml"
            nodes.write_text('proxies: [{name: ProviderNode, type: ss, server: 127.0.0.1, port: 9, cipher: aes-128-gcm, password: private-fixture}]\n')
            nodes.chmod(0o600)
            rule_file = root / "rules/sites.txt"
            rule_file.write_text('example.com\n')
            rule_file.chmod(0o600)
            source.write_text('''mixed-port: 1
secret: provider-secret
proxies: [{name: Imported, type: ss, server: 127.0.0.1, port: 9, cipher: aes-128-gcm, password: private-fixture}]
proxy-providers: {Local: {type: file, path: ./providers/local.yaml}}
proxy-groups:
- {name: 自动, type: url-test, use: [Local], proxies: [Imported], url: "https://example.com", interval: 300}
- {name: 出口, type: select, proxies: [自动, Imported, DIRECT]}
rule-providers: {Sites: {type: file, behavior: domain, format: text, path: ./rules/sites.txt}}
rules: ["RULE-SET,Sites,出口", "MATCH,出口"]
''')
            source.chmod(0o600)
            with patch.dict(os.environ, {"MIHOMO_CORE_BIN": CORE, "XDG_DATA_HOME": str(root / "data")}):
                initialize(config, str(root))
                _, initial, _ = read_config(config)
                endpoint(initial)
                sub = Subscriptions(config, str(root))
                plan = sub.preview(source_file=source, policy="provider")
                sub.apply(plan["id"], plan["sha256"])
                _, final, _ = read_config(config)
                self.assertEqual([g["name"] for g in final["proxy-groups"]], ["自动", "出口"])
                self.assertEqual(final["external-controller"], initial["external-controller"])
                self.assertEqual(final["secret"], initial["secret"])
                self.assertEqual(final["mixed-port"], 25000)
                self.assertEqual(final["rules"], ["RULE-SET,Sites,出口", "MATCH,出口"])
                self.assertEqual(final["proxy-providers"]["Local"]["type"], "file")
                self.assertEqual(final["rule-providers"]["Sites"]["path"], "./rules/sites.txt")
                source.write_text('rules: ["MATCH,GLOBAL"]\n')
                plan = sub.preview(source_file=source, policy="provider")
                sub.apply(plan["id"], plan["sha256"])
                self.assertEqual(read_config(config)[1]["rules"], ["MATCH,GLOBAL"])
                source.write_text('proxy-groups: [{name: GLOBAL, type: select, proxies: [DIRECT]}]\nrules: ["MATCH,GLOBAL"]\n')
                plan = sub.preview(source_file=source, policy="provider")
                sub.apply(plan["id"], plan["sha256"])
                self.assertEqual(read_config(config)[1]["proxy-groups"][0]["name"], "GLOBAL")

    def test_authenticated_core_selection_mode_and_node_transaction(self):
        with tempfile.TemporaryDirectory(prefix="muc-real-core-") as folder:
            root = Path(folder)
            with socket.socket() as one, socket.socket() as two:
                one.bind(("127.0.0.1", 0)); two.bind(("127.0.0.1", 0))
                mixed, controller = one.getsockname()[1], two.getsockname()[1]
            token = secrets.token_urlsafe(40)
            config = root / "config.yaml"
            config.write_text('''mixed-port: {}
bind-address: 127.0.0.1
allow-lan: false
external-controller: 127.0.0.1:{}
secret: {}
authentication: [fixture:private-fixture-password]
mode: rule
log-level: info
geo-auto-update: false
proxies: []
proxy-groups: [{{name: Proxy, type: select, proxies: [DIRECT, REJECT]}}]
rules: ["MATCH,Proxy"]
'''.format(mixed, controller, token))
            config.chmod(0o600)
            environment = dict(os.environ, MIHOMO_CORE_BIN=CORE, XDG_DATA_HOME=str(root / "data"))
            validation = subprocess.run([CORE, "-t", "-d", str(root), "-f", str(config)], capture_output=True, timeout=20)
            self.assertEqual(validation.returncode, 0, "real-core fixture failed validation")
            process = subprocess.Popen([CORE, "-d", str(root), "-f", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                service = ConsoleService(config, str(root))
                deadline = time.monotonic() + 15
                while True:
                    try:
                        rows = service.read("proxies")
                        if rows.get("Proxy", {}).get("selectable"):
                            break
                    except Exception:
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail("real core did not become authenticated/loopback ready")
                        time.sleep(.1)
                self.assertEqual(service.read("proxies")["Proxy"]["type"], "Selector")
                self.assertEqual(service.choose("Proxy", "REJECT")["existing_connections"], "unchanged")
                self.assertEqual(service.mode("direct")["scope"], "runtime-only")
                self.assertGreaterEqual(service.read("memory")["inuse"], 0)
                self.assertIsInstance(service.read("connections")["connections"], list)
                self.assertIsInstance(service.read("rules")["types"], dict)
                with patch.object(runtime, "service_properties", return_value={"MainPID": str(process.pid), "ControlGroup": "", "ActiveState": "active"}):
                    runtime.gate("fixture", [mixed, controller], after=True)
                source = root / "nodes.yaml"
                source.write_text('proxies: [{name: Imported, type: ss, server: 127.0.0.1, port: 9, cipher: aes-128-gcm, password: private-fixture}]\n')
                source.chmod(0o600)
                with patch.dict(os.environ, environment):
                    subscriptions = Subscriptions(config, str(root))
                    preview = subscriptions.preview(source_file=source)
                    result = subscriptions.apply(preview["id"], preview["sha256"])
                self.assertEqual(result["state"], "restart-required")
                self.assertNotIn("Imported", service.read("proxies"))
                self.assertNotIn(token, str(service.read("overview")))
            finally:
                process.terminate()
                process.wait(timeout=10)
