"""Daemon injection regressions; all process/service/network effects are disposable substitutes."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if sys.platform != "linux":
    raise unittest.SkipTest("Paseo daemon integration requires Linux /proc and flock")

from scripts import paseo as p, diagnostics as d, acceptance as a, install_support as installer


ROOT = Path(__file__).resolve().parents[1]
HTTP = "http://fixture-user:private-value@127.0.0.1:28443"
SOCKS = "socks5h://fixture-user:private-value@127.0.0.1:28443"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-paseo-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "paseo-home"
        self.home.mkdir(mode=0o700)
        self.cfg = self.root / "config"
        self.cfg.mkdir(mode=0o700)
        env = {"HOME": str(self.root), "XDG_CONFIG_HOME": str(self.cfg),
               "XDG_STATE_HOME": str(self.root / "state"), "PATH": "/usr/bin:/bin",
               "MIHOMO_PORT": "28443", "MIHOMO_SERVICE": "mihomo",
               "MIHOMO_READY_URL": "https://example.com/", "MIHOMO_HTTP_PROXY": HTTP,
               "MIHOMO_HTTPS_PROXY": HTTP, "MIHOMO_ALL_PROXY": SOCKS,
               "MIHOMO_USERCTL_BIN": str(self.root / "bin/mihomoctl")}
        self.environ = patch.dict(os.environ, env, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def put(self, path, text, mode=0o600):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)
        return path

    def config(self, **kwargs):
        return self.put(self.cfg / "mihomo/paseo-proxy.json", json.dumps(kwargs))


class EnvironmentTests(Fixture):
    def test_default_pairs_required_bypass_and_no_internal_credentials(self):
        expected, pending = p.proxy_environment()
        self.assertFalse(pending)
        for upper in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            self.assertEqual(expected[upper], expected[upper.lower()])
        self.assertTrue(set(p.MANDATORY + p.DIRECT) <= set(expected["NO_PROXY"].split(",")))
        os.environ.update(PASEO_HOST="remote:6767", HTTPS_PROXY="old", MIHOMO_SECRET="private-value")
        env = p.launch_environment(expected, self.home)
        self.assertNotIn("PASEO_HOST", env)
        self.assertFalse(any(x.startswith("MIHOMO_") for x in env))
        self.assertEqual(env["HTTPS_PROXY"], HTTP)

    def test_jsonc_and_approved_baseurls_only(self):
        self.put(self.cfg / "opencode/opencode.jsonc", '''{
          // URL and commas inside strings must survive
          "provider": {
            "coding": {"options": {"baseURL":"https://coding.bigmodel.cn/v4//route?q=,}", "apiKey":"never-output"}},
            "overseas": {"options": {"baseURL":"https://api.openai.com/v1"}},
            "custom": {"options": {"baseURL":"https://unapproved.example/v1"}},
          },
        }''')
        expected, pending = p.proxy_environment()
        self.assertIn("coding.bigmodel.cn", expected["NO_PROXY"])
        self.assertNotIn("api.openai.com", expected["NO_PROXY"])
        self.assertEqual(pending, ["unapproved.example"])
        self.assertNotIn("never-output", repr((expected, pending)))

    def test_explicit_override_files_env_urls_and_inline(self):
        custom = self.put(self.root / "custom.json", '{"provider":{"x":{"options":{"baseURL":"{env:BASE_URL}"}}}}')
        self.config(direct_domains=["direct.example"], opencode_allowed_domains=["example.cn"],
                    opencode_config_files=[str(custom)])
        os.environ["BASE_URL"] = "https://api.example.cn/v1"
        os.environ["OPENCODE_CONFIG_CONTENT"] = '{"provider":{"x":{"options":{"baseURL":"https://direct.example/v1"}}}}'
        expected, _ = p.proxy_environment()
        self.assertIn("api.example.cn", expected["NO_PROXY"])
        self.assertIn("direct.example", expected["NO_PROXY"])

    def test_invalid_permissions_symlinks_and_domains(self):
        for value in ("*", ".openai.com", "openai.com", "api.openai.com", "com", "chatgpt.com", "github.com", "https://api.deepseek.com"):
            with self.subTest(value=value):
                self.config(direct_domains=[value])
                with self.assertRaises(d.DiagnosticError):
                    p.proxy_environment()
        path = self.config(direct_domains=[])
        path.chmod(0o644)
        with self.assertRaises(d.DiagnosticError):
            p.proxy_environment()
        path.unlink()
        path.symlink_to(self.put(self.root / "other", "{}"))
        with self.assertRaises(d.DiagnosticError):
            p.proxy_environment()

    def test_invalid_json_unknown_keys_and_unresolved_urls(self):
        for text in ("{", '{"unknown":[]}', '{"direct_domains":"bad"}'):
            self.put(self.cfg / "mihomo/paseo-proxy.json", text)
            with self.assertRaises(d.DiagnosticError):
                p.proxy_environment()
        self.config()
        self.put(self.cfg / "opencode/opencode.json", '{"provider":{"x":{"options":{"baseURL":"{env:MISSING}"}}}}')
        with self.assertRaises(d.DiagnosticError):
            p.proxy_environment()


class ProbeTests(Fixture):
    def response(self, http=403, connect=200, ip="127.0.0.1", port=28443, rc=0):
        return subprocess.CompletedProcess([], rc, "{:03d}\t{:03d}\t{}\t{}\t0.6".format(http, connect, ip, port), "private-value")

    def test_target_403_and_421_are_network_evidence_not_models(self):
        for http in (403, 421, 401, 200):
            with patch.object(a, "run_command", return_value=self.response(http)) as run:
                row = p.target_probe(p.TARGETS[0], 28443, HTTP)
                self.assertEqual(row["status"], "PASS")
                self.assertEqual(row["tls"], "PASS")
                self.assertNotIn("private-value", repr(row))
                self.assertNotIn(HTTP, repr(run.call_args.args[0]))
                self.assertEqual(run.call_args.args[2]["https_proxy"], HTTP)

    def test_auth_failure_wrong_peer_and_curl_error_are_not_passes(self):
        for kwargs in ({"http":407}, {"connect":407}, {"ip":"192.0.2.1"}, {"port":28444}, {"rc":60}, {"rc":28,"http":0}):
            with self.subTest(kwargs=kwargs), patch.object(a, "run_command", return_value=self.response(**kwargs)):
                self.assertEqual(p.target_probe(p.TARGETS[0], 28443, HTTP)["status"], "FAIL")
        with patch.object(a, "run_command", return_value=None):
            self.assertEqual(p.target_probe(p.TARGETS[0], 28443, HTTP)["status"], "UNVERIFIED")

    def test_proxy_failure_skips_target_probes_and_invalid_credentials_skip_all(self):
        expected, _ = p.proxy_environment()
        with patch.object(a, "service_active_check", return_value=a.Result("FAIL", "service", "fixture")), \
                patch.object(a, "listener_check", return_value=a.Result("PASS", "listener", "fixture")), \
                patch.object(p, "target_probe") as probe:
            self.assertEqual(p.network(expected)[0], "FAIL")
            probe.assert_not_called()
        expected["HTTPS_PROXY"] = "http://private-value@other:28443"
        with patch.object(a, "service_active_check") as service, self.assertRaises(d.DiagnosticError):
            p.network(expected)
        service.assert_not_called()

    def test_direct_success_is_informational_and_drift_still_blocks(self):
        expected, pending = p.proxy_environment()
        daemon = {"running":False,"inspection":"PASS","environment":"PASS","ready":False,
                  "processes":[],"identities":{}}
        rows = [{"path":"direct","status":"PASS","http":403}]
        with patch.object(p, "network", return_value=("PASS", [], rows)), patch.object(p, "snapshot", return_value=daemon):
            overall, payload, _ = p.preflight("fixture", self.home, expected, pending)
            self.assertEqual(overall, "SAFE_TO_LAUNCH")
            self.assertEqual(payload["model_request"], "UNVERIFIED")
            self.assertEqual(payload["injection_necessity"], "NOT_DEMONSTRATED")
            daemon.update(running=True, ready=True, environment="FAIL")
            self.assertEqual(p.preflight("fixture", self.home, expected, pending)[0], "BLOCKED")
            daemon["inspection"] = "UNVERIFIED"
            self.assertEqual(p.preflight("fixture", self.home, expected, pending)[0], "UNVERIFIED")


class ProcessTests(Fixture):
    def setUp(self):
        super().setUp()
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.expected, _ = p.proxy_environment()
        self.observed = {"home":str(self.home),"pid":42,"workerPid":43,"localDaemon":"running","connectedDaemon":"reachable"}

    def process(self, pid, parent, role, env=None, uid=None):
        path = self.proc / str(pid)
        path.mkdir(exist_ok=True)
        uid = os.getuid() if uid is None else uid
        self.put(path / "status", "Uid:\t{0} {0} {0} {0}\nPPid:\t{1}\n".format(uid, parent))
        self.put(path / "stat", str(pid) + " (fixture) S " + " ".join([str(parent)] + ["0"] * 17 + [str(pid * 100)]))
        self.put(path / "cmdline", ("Paseo Supervisor" if role == "supervisor" else "Paseo Daemon") + "\0")
        self.put(path / "environ", "\0".join(k + "=" + v for k, v in (self.expected if env is None else env).items()) + "\0")
        return path

    def check(self):
        with patch.object(p, "status", return_value=self.observed):
            return p.snapshot("fixture", self.home, self.expected, self.proc)

    def test_supervisor_worker_and_home_scoping(self):
        self.process(42, 100, "supervisor")  # PPID need not be 1.
        self.process(43, 42, "worker")
        self.process(44, 1, "supervisor", env={})
        result = self.check()
        self.assertEqual(result["inspection"], "PASS")
        self.assertEqual(result["environment"], "PASS")
        self.assertEqual([x["pid"] for x in result["processes"]], [42,43])
        self.assertNotIn("private-value", repr(p.public_snapshot(result)))
        self.observed.pop('workerPid')
        self.assertEqual(self.check()['inspection'],'PASS')

    def test_unit_ownership_requires_each_process_in_the_expected_cgroup(self):
        self.process(42,1,'supervisor')
        self.process(43,42,'worker')
        daemon=self.check()
        for pid in (42,43):
            self.put(self.proc/str(pid)/'cgroup','0::/user.slice/paseo.service\n')
        with patch.object(p,'PROC',self.proc), patch.object(a,'run_command',return_value=subprocess.CompletedProcess([],0,'/user.slice/paseo.service\n','')):
            self.assertTrue(p.unit_owns_daemon(daemon))
            self.put(self.proc/'43/cgroup','0::/user.slice/unrelated.service\n')
            self.assertFalse(p.unit_owns_daemon(daemon))

    def test_drift_unreadable_duplicate_and_rotated_credentials(self):
        self.process(42, 1, "supervisor")
        worker = self.process(43, 42, "worker", env={})
        self.assertEqual(self.check()["environment"], "FAIL")
        self.process(43, 42, "worker")
        self.expected["HTTPS_PROXY"] = "rotated"
        self.assertEqual(self.check()["environment"], "FAIL")
        worker.joinpath("environ").unlink()
        self.assertEqual(self.check()["inspection"], "UNVERIFIED")
        self.process(43, 42, "worker")
        with worker.joinpath("environ").open("a") as stream:
            stream.write("HTTPS_PROXY=duplicate\0")
        self.assertEqual(self.check()["inspection"], "UNVERIFIED")

    def test_foreign_supervisor_private_data_never_read(self):
        self.process(42, 1, "supervisor", uid=os.getuid()+1)
        with patch.object(d, "read_environment", side_effect=AssertionError("foreign read")), \
                patch.object(p, "argv", side_effect=AssertionError("foreign argv read")):
            self.assertEqual(self.check()["inspection"], "UNVERIFIED")

    def test_identity_change_and_multiple_workers_fail_closed(self):
        self.process(42, 1, "supervisor")
        self.process(43, 42, "worker")
        with patch.object(d, "process_identity", side_effect=[1,2]):
            self.assertEqual(self.check()["inspection"], "UNVERIFIED")
        self.process(45, 42, "worker")
        self.assertEqual(self.check()["inspection"], "UNVERIFIED")

    def test_codex_bypass_exception_is_only_for_validated_descendants(self):
        self.process(42,1,"supervisor")
        self.process(43,42,"worker")
        self.process(44,43,"worker")
        self.process(45,1,"worker")
        result = self.check()
        context = result["identities"], self.expected
        default = d.expected_environment()
        self.assertEqual(p.descendant_environment(self.proc,44,context,default),self.expected)
        self.assertEqual(p.descendant_environment(self.proc,45,context,default),default)

    def test_status_unknown_shape_wrong_home_and_noninteger_pid(self):
        for value in ({}, {**self.observed,"home":"/other"}, {**self.observed,"pid":True}):
            with patch.object(p, "command", return_value=subprocess.CompletedProcess([],0,json.dumps(value),"")):
                with self.assertRaises(d.DiagnosticError):
                    p.status("fixture",self.home)


class UnitTests(Fixture):
    def test_install_is_private_idempotent_no_credentials_and_no_activation(self):
        with patch.object(a,"run_command",return_value=subprocess.CompletedProcess([],0,"","")) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(p.install_unit("/usr/bin/paseo",self.home,False),0)
                self.assertEqual(p.install_unit("/usr/bin/paseo",self.home,False),0)
            self.assertEqual(run.call_count,2)
            self.assertEqual(run.call_args.args[0],["systemctl","--user","daemon-reload"])
        text = p.unit_path().read_text()
        self.assertNotIn("private-value",text)
        self.assertNotIn("HTTP_PROXY=",text)
        self.assertIn("Restart=on-failure",text)
        self.assertIn('"paseo" "run"',text)
        self.assertIn("Requires=mihomo.service",text)
        self.assertEqual(p.unit_path().stat().st_mode & 0o777,0o600)

    def test_dry_run_and_foreign_unit_or_home_refused(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(a,"run_command") as run:
            p.install_unit("/usr/bin/paseo",self.home,True)
            run.assert_not_called()
        self.assertFalse(p.unit_path().exists())
        self.put(p.unit_path(),"[Service]\nExecStart=/other\n")
        with self.assertRaises(d.DiagnosticError):
            p.install_unit("/usr/bin/paseo",self.home,False)
        self.put(p.unit_path(),p.unit_text("/usr/bin/paseo",self.root / "other"))
        with self.assertRaises(d.DiagnosticError):
            p.managed_unit(self.home, strict=True)
        self.assertFalse(p.managed_unit(self.home))

    def test_lock_contention_and_symlink_refused(self):
        with p.lifecycle_lock(self.home):
            with self.assertRaises(d.DiagnosticError):
                with p.lifecycle_lock(self.home):
                    self.fail("second owner")
        lock = next((self.root / "state/mihomo-userctl").glob("*.lock"))
        lock.unlink()
        lock.symlink_to(self.put(self.root / "target","untouched"))
        with self.assertRaises(OSError):
            with p.lifecycle_lock(self.home):
                self.fail("symlink followed")

    def test_historical_inventory_is_frozen_before_new_modules(self):
        self.assertNotIn("paseo.py",installer.RUNTIME_092)
        self.assertNotIn("controller_health.py",installer.RUNTIME_092)
        self.assertIn("paseo.py",installer.RUNTIME.values())

    def test_unsafe_directory_ancestor_is_rejected_before_writing(self):
        unsafe=self.root/'unsafe'
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        with self.assertRaises(d.DiagnosticError):
            p.owned_directory(unsafe/'new')
        self.assertFalse((unsafe/'new').exists())

    def test_systemd_start_releases_lock_before_unit_launch(self):
        stopped = {"running":False,"inspection":"PASS","environment":"PASS","ready":False,"processes":[],"identities":{}}
        def systemctl(args,*rest):
            self.assertEqual(args,["systemctl","--user","start","paseo.service"])
            with p.lifecycle_lock(self.home):
                pass
            return subprocess.CompletedProcess(args,0,"","")
        with patch.object(p,"executable",return_value="/fixture/paseo"), \
                patch.object(p,"network",return_value=("PASS",[],[])), \
                patch.object(p,"snapshot",return_value=stopped), \
                patch.object(p,"managed_unit",return_value=True), \
                patch.object(a,"run_command",side_effect=systemctl), \
                patch.object(p,"unit_owns_daemon",return_value=True), \
                patch.object(p,"wait_ready") as wait:
            self.assertEqual(p.main(["start","--home",str(self.home)]),0)
            wait.assert_called_once()

    def test_systemd_refuses_to_replace_an_unmanaged_running_daemon(self):
        running = {"running":True,"inspection":"PASS","environment":"FAIL","ready":True,"processes":[],"identities":{}}
        with patch.object(p,"executable",return_value="/fixture/paseo"), \
                patch.object(p,"network",return_value=("PASS",[],[])), \
                patch.object(p,"snapshot",return_value=running), \
                patch.object(p,"managed_unit",return_value=True), \
                patch.object(p,"unit_owns_daemon",return_value=False), \
                patch.object(a,"run_command") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.main(["restart","--home",str(self.home)]),2)
            run.assert_not_called()


# This fake CLI and its process tree are Linux processes under a disposable HOME.
# Their code and /proc paths never replace or control a real Paseo installation.
FAKE = r'''#!/usr/bin/python3
import json,os,pathlib,signal,subprocess,sys,time
root=pathlib.Path(os.environ['FIXTURE_ROOT'])
home=pathlib.Path(sys.argv[sys.argv.index('--home')+1]) if '--home' in sys.argv else pathlib.Path(sys.argv[-1])
record=home/'runtime.json'
def read():
 try: return json.loads(record.read_text())
 except (OSError,ValueError): return None
def live(pid):
 try: return pathlib.Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
 except OSError: return False
def wait_record():
 for _ in range(100):
  state=read()
  if state and live(state['pid']): return
  time.sleep(.02)
 sys.exit(4)
if len(sys.argv)>1 and sys.argv[1]=='supervisor':
 worker=subprocess.Popen([sys.executable,str(root/'pkg/@getpaseo/server/index.js'),str(home)])
 record.write_text(json.dumps(dict(home=str(home),pid=os.getpid(),workerPid=worker.pid,localDaemon='running',connectedDaemon='reachable')))
 def stop(*a):
  worker.terminate();worker.wait(timeout=3)
  if record.exists() and read()['pid']==os.getpid(): record.unlink()
  sys.exit(0)
 signal.signal(signal.SIGTERM,stop)
 while True: time.sleep(.05)
action=sys.argv[2]
if action=='status':
 state=read()
 print(json.dumps(state if state and live(state['pid']) else dict(home=str(home),pid=None,localDaemon='stopped',connectedDaemon='not_probed')))
elif action=='stop':
 with (root/'actions').open('a') as f:f.write('stop\n')
 if (root/'stop-fails').exists():sys.exit(3)
 state=read()
 if state and live(state['pid']):
  os.kill(state['pid'],signal.SIGTERM)
  for _ in range(100):
   if not live(state['pid']):break
   time.sleep(.02)
elif action in ('start','run'):
 with (root/'actions').open('a') as f:f.write(action+'\n')
 if (root/'start-fails').exists():sys.exit(3)
 state=read()
 if state and live(state['pid']):sys.exit(0)
 child=subprocess.Popen([sys.executable,str(root/'pkg/@getpaseo/server/supervisor-entrypoint.js'),'supervisor',str(home)],start_new_session=action=='start',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 wait_record()
 if action=='run':
  signal.signal(signal.SIGTERM,lambda *a:child.send_signal(signal.SIGTERM))
  sys.exit(child.wait())
'''
WORKER = r'''import os,pathlib,signal,subprocess,sys,time
root=pathlib.Path(os.environ['FIXTURE_ROOT'])
child=subprocess.Popen([str(root/'bin/codex'),'app-server'])
def stop(*a):
 child.terminate();child.wait(timeout=3);sys.exit(0)
signal.signal(signal.SIGTERM,stop)
while True:time.sleep(.05)
'''
CODEX = r'''#!/usr/bin/python3
import ctypes,signal,time
ctypes.CDLL(None).prctl(15,b'codex',0,0,0)
signal.signal(signal.SIGTERM,lambda *a:exit(0))
while True:time.sleep(.05)
'''
CURL = r'''#!/usr/bin/python3
import os,pathlib,sys
root=pathlib.Path(os.environ['FIXTURE_ROOT']);proxy=bool(os.environ.get('https_proxy'))
if 'time_total' not in sys.argv[sys.argv.index('--write-out')+1]:
 print('204\t200\t127.0.0.1\t28443');sys.exit(0)
if proxy:
 print('403\t200\t127.0.0.1\t28443\t0.6');sys.exit(1 if (root/'proxy-fails').exists() else 0)
print('000\t000\t192.0.2.1\t443\t0.01');sys.exit(28)
'''


@unittest.skipUnless(sys.platform == "linux", "real process regression requires Linux /proc")
class LifecycleTests(Fixture):
    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.lib = self.root / "lib"
        self.lib.mkdir(mode=0o700)
        for name in ("paseo.py","diagnostics.py","acceptance.py","reporting.py"):
            shutil.copyfile(ROOT / "scripts" / name,self.lib / name)
        shutil.copyfile(ROOT / "src/common.bash",self.lib / "common.bash")
        module = self.lib / "acceptance.py"
        module.write_text(module.read_text()+ '\nhttp_no_auth=lambda *a:Result("PASS","http-no-auth","fixture-407")\nsocks_no_auth=lambda *a:Result("PASS","socks5h-no-auth","fixture-ff")\n')
        self.put(self.bin / "mihomoctl",(ROOT / "src/mihomoctl").read_text(),0o755)
        self.put(self.bin / "paseo",FAKE,0o755)
        self.put(self.root / "pkg/@getpaseo/server/supervisor-entrypoint.js",FAKE,0o755)
        self.put(self.root / "pkg/@getpaseo/server/index.js",WORKER,0o755)
        self.put(self.bin / "codex",CODEX,0o755)
        self.put(self.bin / "curl",CURL,0o755)
        self.put(self.bin / "systemctl",'#!/bin/sh\ncase "$*" in *--quiet*) exit 0;; *is-enabled*) printf "disabled\\n"; exit 1;; *) printf "active\\n";; esac\n',0o755)
        self.put(self.bin / "ss","#!/bin/sh\nprintf 'LISTEN 0 4096 127.0.0.1:28443 0.0.0.0:*\\n'\n",0o755)
        self.put(self.cfg / "mihomo/mihomo-shell.conf","MIHOMO_SERVICE=mihomo\nMIHOMO_PORT=28443\nMIHOMO_READY_URL=https://example.com/\n")
        self.put(self.cfg / "mihomo/client.env","MIHOMO_HTTP_PROXY='"+HTTP+"'\nMIHOMO_HTTPS_PROXY='"+HTTP+"'\nMIHOMO_ALL_PROXY='"+SOCKS+"'\n")
        os.environ.update(PATH=str(self.bin)+":/usr/bin:/bin",PASEO_HOME=str(self.home),
                          FIXTURE_ROOT=str(self.root),MIHOMO_USERCTL_LIB_DIR=str(self.lib))
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        (self.root / "stop-fails").unlink(missing_ok=True)
        subprocess.run([str(self.bin / "paseo"),"daemon","stop","--home",str(self.home)],
                       capture_output=True,timeout=8)

    def cli(self,*args,expected=None):
        result = subprocess.run([str(self.bin / "mihomoctl"),"paseo",*args],capture_output=True,text=True,timeout=30)
        self.assertNotIn("private-value",result.stdout+result.stderr)
        if expected is not None:self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return result

    def status(self):
        return json.loads((self.home / "runtime.json").read_text())

    def test_start_idempotence_restart_new_processes_and_eight_variables(self):
        self.cli("preflight","--json",expected=0)
        self.assertFalse((self.root / "actions").exists())
        self.cli("start",expected=0)
        old = self.status()
        self.cli("start",expected=0)
        self.assertEqual(old,self.status())
        expected,_=p.proxy_environment()
        for pid in (old['pid'],old['workerPid']):
            self.assertEqual(d.read_environment(Path('/proc'),pid),{k:v.encode() for k,v in expected.items()})
        self.cli("restart",expected=0)
        self.assertNotEqual(old['pid'],self.status()['pid'])
        self.assertNotEqual(old['workerPid'],self.status()['workerPid'])
        self.assertEqual((self.root / "actions").read_text().splitlines(),['start','stop','start'])
        self.cli("preflight","--json",expected=0)

    def test_direct_daemon_requires_explicit_restart_and_codex_compatibility(self):
        env=p.launch_environment({},self.home)
        subprocess.run([str(self.bin / "paseo"),"daemon","start","--home",str(self.home)],env=env,capture_output=True,check=True)
        old=self.status()['pid']
        data=json.loads(self.cli("preflight","--json",expected=1).stdout)
        self.assertFalse(data['launch_safe'])
        self.cli("start",expected=1)
        self.assertEqual(old,self.status()['pid'])
        self.cli("exec","--","/bin/true",expected=1)
        self.cli("restart",expected=0)
        time.sleep(.1)
        context=p.codex_context(Path('/proc'))
        self.assertIsNotNone(context)
        processes,_=d.codex_snapshot()
        rows=[x for x in processes if p.descendant_environment(Path('/proc'),x['pid'],context,{})]
        self.assertTrue(rows)
        self.assertTrue(all(x['proxy_environment']['classification']=='proxied' for x in rows))

    def test_stop_failure_and_proxy_failure_never_start_replacement(self):
        self.cli("start",expected=0)
        old=self.status()['pid']
        self.put(self.root / "stop-fails", "")
        self.cli("restart",expected=2)
        self.assertEqual(old,self.status()['pid'])
        self.put(self.root / "proxy-fails", "")
        self.cli("restart",expected=1)
        self.assertEqual(old,self.status()['pid'])
        self.assertEqual((self.root / "actions").read_text().splitlines(),['start','stop'])

    def test_start_failure_and_exec_literal_arguments_and_exit_status(self):
        self.put(self.root / "start-fails", "")
        self.cli("start",expected=2)
        command=self.put(self.bin / "capture",'#!/usr/bin/python3\nimport json,os,sys\nassert not any(k.startswith("MIHOMO_") for k in os.environ)\nassert os.environ["HTTP_PROXY"]==os.environ["http_proxy"]\nprint(json.dumps(sys.argv[1:]));sys.exit(37)\n',0o755)
        result=self.cli("exec","--",str(command),"a b","$(touch never)",expected=37)
        self.assertEqual(json.loads(result.stdout),['a b','$(touch never)'])
        self.assertFalse((self.root / "never").exists())

    def test_foreground_signal_shutdown_and_duplicate_run_refusal(self):
        proc=subprocess.Popen([str(self.bin/'mihomoctl'),'paseo','run'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+10
            while not (self.home/'runtime.json').exists():
                if time.monotonic()>deadline:self.fail('foreground failed to start')
                time.sleep(.05)
            time.sleep(.7)
            self.cli('run',expected=1)
            proc.send_signal(signal.SIGTERM)
            out,err=proc.communicate(timeout=12)
            self.assertEqual(proc.returncode,0,out+err)
            self.assertFalse((self.home/'runtime.json').exists())
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                proc.communicate(timeout=12)

    def test_doctor_offline_reports_drift_and_disabled_codex_skips(self):
        subprocess.run([str(self.bin/'paseo'),'daemon','start','--home',str(self.home)],
                       env=p.launch_environment({},self.home),capture_output=True,check=True)
        result=self.cli('doctor','--offline','--json',expected=1)
        self.assertEqual(json.loads(result.stdout)['dependency_evidence'],'configuration-only')
        self.put(self.home/'config.json','{"agents":{"providers":{"codex":{"enabled":false}}}}')
        self.assertEqual(json.loads(self.cli('doctor','--offline','--json',expected=0).stdout)['status'],'SKIPPED')

    def test_invalid_options_and_credentials_do_not_start(self):
        for args in (('start','--host','remote'),('exec',),('start','--json'),('preflight','--','/bin/true')):
            self.cli(*args,expected=2)
        self.put(self.cfg/'mihomo/client.env','MIHOMO_HTTP_PROXY=invalid\n')
        self.cli('preflight','--json',expected=2)
        self.assertFalse((self.root/'actions').exists())

    def test_concurrent_cli_operation_does_not_launch(self):
        with p.lifecycle_lock(self.home):
            self.cli('start',expected=2)
        self.assertFalse((self.root/'actions').exists())

    def test_credential_rotation_requires_complete_supervisor_replacement(self):
        self.cli('start',expected=0)
        old=self.status()['pid']
        path=self.cfg/'mihomo/client.env'
        path.write_text(path.read_text().replace('private-value','rotated-fixture'))
        self.cli('preflight','--json',expected=1)
        self.cli('restart',expected=0)
        self.assertNotEqual(old,self.status()['pid'])
        values=d.read_environment(Path('/proc'),self.status()['workerPid'])
        self.assertIn(b'rotated-fixture',values['HTTPS_PROXY'])

    def test_top_level_doctor_json_contains_redacted_daemon_drift(self):
        subprocess.run([str(self.bin/'paseo'),'daemon','start','--home',str(self.home)],
                       env=p.launch_environment({},self.home),capture_output=True,check=True)
        result=subprocess.run([str(self.bin/'mihomoctl'),'doctor','--offline','--json'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertTrue(result.stdout.lstrip().startswith('{'),repr(result.stdout)+result.stderr)
        document=json.loads(result.stdout)
        self.assertEqual(document['agent_daemon']['status'],'FAIL')
        self.assertNotIn('private-value',result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
