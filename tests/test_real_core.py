"""Opt-in real Mihomo integration; never installs a service or uses root."""
import os
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socketserver
import threading
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

from mihomoctl.controller.controller_service import ConsoleService
from mihomoctl.controller.controller_subscriptions import Subscriptions
from mihomoctl.controller import controller_runtime as runtime


class RealCoreTests(unittest.TestCase):
    def test_trusted_geodata_copy_validates_offline_and_missing_or_corrupt_cache_fails_safely(self):
        from mihomoctl.lifecycle.runner import validate_config
        from mihomoctl.errors import MihomoctlError
        import hashlib
        import json
        fixture = Path(__file__).parent/'fixtures/geodata'
        for record in json.loads((fixture/'sources.json').read_text()):
            self.assertEqual(hashlib.sha256((fixture/record['file']).read_bytes()).hexdigest(), record['sha256'])
        with tempfile.TemporaryDirectory(prefix='muc-real-geodata-') as folder:
            home = Path(folder)
            data = (fixture/'GeoIP2-Country-Test.mmdb').read_bytes()
            cache = home/'geoip.metadb'; cache.write_bytes(data); cache.chmod(0o600)
            text = ('geo-auto-update: false\ngeodata-mode: false\ngeox-url:\n'
                    '  mmdb: http://127.0.0.1:9/PRIVATE-CACHE-URL\n'
                    'rules: ["GEOIP,GB,DIRECT,no-resolve", "MATCH,DIRECT"]\n')
            self.assertTrue(validate_config(CORE, text, home, timeout=8))
            self.assertEqual(cache.read_bytes(), data)
            cache.unlink()
            for content in (None, b'corrupt-database'):
                if content is not None: cache.write_bytes(content); cache.chmod(0o600)
                with self.assertRaises(MihomoctlError) as caught:
                    validate_config(CORE, text, home, timeout=8)
                self.assertNotIn('PRIVATE-CACHE-URL', str(caught.exception))
                self.assertIn('stage=core-validation', caught.exception.detail)

    def test_provider_only_nodes_real_single_batch_duplicate_names_and_refresh_removal(self):
        import yaml
        from mihomoctl.controller.controller_api import Client
        from mihomoctl.controller import controller_service as svc
        from mihomoctl.controller.controller_types import ControlError
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(.02); self.send_response(204); self.end_headers()
            do_HEAD = do_GET
            def log_message(self, *args): pass
        target = ThreadingHTTPServer(('127.0.0.1',0), Target)
        threading.Thread(target=target.serve_forever,daemon=True).start()
        self.addCleanup(target.server_close); self.addCleanup(target.shutdown)
        with tempfile.TemporaryDirectory(prefix='muc-real-provider-') as folder:
            root=Path(folder)
            def write_provider(path, nodes):
                path.write_text(yaml.safe_dump({'proxies':[{'name':n,'type':'direct'} for n in nodes]}));path.chmod(0o600)
            names=['节点 / +?% '+str(i) for i in range(44)]
            first,second=root/'first.yaml',root/'second.yaml'
            write_provider(first,names);write_provider(second,[names[0]])
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            secret=secrets.token_urlsafe(32)
            config={'external-controller':'127.0.0.1:'+str(port),'secret':secret,'geo-auto-update':False,
                    'proxy-providers':{'订阅 /?%':{'type':'file','path':'first.yaml'},'second':{'type':'file','path':'second.yaml'}},
                    'proxy-groups':[{'name':'Ai+','type':'select','use':['订阅 /?%']}], 'rules':['MATCH,DIRECT']}
            path=root/'config.yaml';path.write_text(yaml.safe_dump(config,allow_unicode=True));path.chmod(0o600)
            from mihomoctl.lifecycle.runner import child_environment
            process=subprocess.Popen([CORE,'-d',str(root),'-f',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=child_environment())
            try:
                client=Client(port,secret)
                deadline=time.monotonic()+8
                while True:
                    try: client.verify();break
                    except ControlError:
                        if time.monotonic()>deadline: raise
                        time.sleep(.05)
                self.assertEqual(client.request('/version')['version'].lstrip('v'),'1.19.32')
                service=ConsoleService(path,str(root))
                with patch.object(service,'client',return_value=client), patch.object(svc,'TEST_URL','http://127.0.0.1:'+str(target.server_port)+'/'):
                    nodes=svc.snapshot(client,'nodes')['nodes']
                    self.assertEqual(sum(n.get('provider')=='订阅 /?%' for n in nodes),44)
                    self.assertEqual(svc.proxies(client)['Ai+']['missing_member_count'],0)
                    self.assertGreater(service.latency(names[1])['delay_ms'],0)
                    with self.assertRaisesRegex(ControlError,'ambiguous-node'): service.latency(names[0])
                    batch=service.batch_latency([{'name':names[0],'provider':p} for p in ('订阅 /?%','second')])
                    self.assertEqual(batch['target_count'],2)
                    self.assertTrue(all(r['state']=='success' for r in batch['results']))
                    write_provider(first,[names[1]])
                    service.provider_refresh('订阅 /?%')
                    with self.assertRaisesRegex(ControlError,'unknown-node'): service.latency(names[2])
            finally:
                process.terminate();process.wait(timeout=10)

    def test_local_url_test_failover_and_all_failed_evidence(self):
        """Two controllable CONNECT proxies, a local target, and a real core."""
        class Target(BaseHTTPRequestHandler):
            def do_HEAD(self):
                # v1.19.32 rounds down to milliseconds and treats a zero
                # LastDelayForTestUrl as 0xffff even when the probe is alive.
                # A real positive baseline is required for fastest selection.
                time.sleep(.02)
                self.send_response(204)
                self.end_headers()
            do_GET = do_HEAD
            def log_message(self, *args):
                pass

        class Proxy(socketserver.StreamRequestHandler):
            def handle(self):
                if self.server.failed.is_set():
                    return
                first = self.rfile.readline().decode("ascii").split()
                if len(first) < 2 or first[0] != "CONNECT":
                    return
                while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                    pass
                # Only the test's loopback target is allowed, no external network.
                if first[1] != "127.0.0.1:" + str(target.server_port):
                    return
                with socket.create_connection(("127.0.0.1", target.server_port), timeout=2) as upstream:
                    self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    while not self.server.failed.is_set():
                        readable, _, _ = select.select([self.connection, upstream], [], [], .1)
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is self.connection else self.connection).sendall(data)

        class ProxyServer(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        servers = [target]
        for _ in range(2):
            server = ProxyServer(("127.0.0.1", 0), Proxy)
            server.failed = threading.Event()
            servers.append(server)
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix="muc-real-failover-") as folder:
                root = Path(folder)
                with socket.socket() as one, socket.socket() as two:
                    one.bind(("127.0.0.1", 0)); two.bind(("127.0.0.1", 0))
                    mixed, controller = one.getsockname()[1], two.getsockname()[1]
                token = secrets.token_urlsafe(40)
                config = root / "config.yaml"
                config.write_text('''mixed-port: {mixed}
bind-address: 127.0.0.1
allow-lan: false
external-controller: 127.0.0.1:{controller}
secret: {token}
geo-auto-update: false
log-level: error
proxies:
- {{name: A, type: http, server: 127.0.0.1, port: {one}}}
- {{name: B, type: http, server: 127.0.0.1, port: {two}}}
proxy-groups:
- {{name: Auto, type: url-test, proxies: [A, B], url: "http://127.0.0.1:{target}/204", expected-status: 204, interval: 1, timeout: 300, tolerance: 50, lazy: false}}
- {{name: Entry, type: select, proxies: [Auto, A]}}
rules: ["MATCH,Entry"]
'''.format(mixed=mixed, controller=controller, token=token,
           one=servers[1].server_address[1], two=servers[2].server_address[1], target=target.server_port))
                config.chmod(0o600)
                check = subprocess.run([CORE, "-t", "-d", str(root), "-f", str(config)], capture_output=True, timeout=20)
                self.assertEqual(check.returncode, 0, "failover fixture must validate")
                process = subprocess.Popen([CORE, "-d", str(root), "-f", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    service = ConsoleService(config, str(root))
                    def wait_for(predicate, description, budget=15):
                        deadline = time.monotonic() + budget
                        while time.monotonic() < deadline:
                            try:
                                rows = service.read("proxies")
                                if predicate(rows):
                                    return rows
                            except Exception:
                                if process.poll() is not None:
                                    self.fail("real core exited during " + description)
                            time.sleep(.2)
                        self.fail("real core timed out during " + description)
                    rows = wait_for(lambda r: all(r.get(n, {}).get("probe_observed") for n in ("A", "B")), "initial probes")
                    probe_url='http://127.0.0.1:{}/204'.format(target.server_port)
                    raw=service.client().request('/proxies')['proxies']
                    for name in ('A','B'):
                        evidence=raw[name]['extra'][probe_url]
                        self.assertIs(evidence['alive'],True,'initial local probe must be healthy')
                        self.assertTrue(0<evidence['history'][-1]['delay']<0xffff,'initial probe must have a usable positive millisecond delay')
                    chosen = rows["Auto"]["selected"]
                    healthy = "B" if chosen == "A" else "A"
                    servers[1 if chosen == "A" else 2].failed.set()
                    started = time.monotonic()
                    wait_for(lambda r: r["Auto"]["selected"] == healthy, "automatic failover")
                    self.assertLess(time.monotonic() - started, 15, "allow interval, timeout and core selection cache")
                    connection = http.client.HTTPConnection("127.0.0.1", mixed, timeout=3)
                    try:
                        connection.request("GET", "http://127.0.0.1:{}/204".format(target.server_port))
                        self.assertEqual(connection.getresponse().status, 204)
                    finally:
                        connection.close()
                    servers[1 if healthy == "A" else 2].failed.set()
                    rows = wait_for(lambda r: r["Auto"]["probe_state"] == "all-observed-failed", "all probes failed")
                    self.assertIn("all-observed-failed", rows["Auto"]["warnings"])
                finally:
                    process.terminate()
                    process.wait(timeout=10)
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()

    def test_initialize_and_provider_policy_validate_with_real_core(self):
        from mihomoctl.controller.controller_dashboard import initialize
        from mihomoctl.controller.controller_config import read_config, endpoint
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
