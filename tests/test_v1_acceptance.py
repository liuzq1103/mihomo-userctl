"""Mandatory disposable-VM acceptance: real users, systemd, core and TUN.

Local test discovery skips this class. Its explicit CI entry point refuses missing
prerequisites and any skipped test. Never run against a production host.
"""
import base64
from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ENABLED = os.environ.get("MIHOMO_V1_PRIVILEGED") == "1"
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy")
# The repository's own release identity; the acceptance run must follow the
# manifest it is actually installing instead of a hard-coded literal.
REPOSITORY_VERSION = json.loads(
    (Path(__file__).resolve().parents[1] / "release-manifest.json").read_text(encoding="utf-8"))["version"]


def command(argv, **kwargs):
    allowed = kwargs.pop("allowed", (0,))
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                            timeout=kwargs.pop("timeout", 60), **kwargs)
    if result.returncode not in allowed:
        # Do not copy raw config/credentials or command stdout into CI logs.
        match = re.search(r"^bootstrap: ([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?=:|$)",
                          result.stderr, re.MULTILINE)
        code = match.group(1) if match else "unparsed-tool-error"
        if "bootstrap: untrusted installation code path" in result.stderr:
            code = "bootstrap-code-untrusted"
        causes = re.search(r"^bootstrap: failure-codes=([a-z-]+(?:,[a-z-]+)*)$",
                           result.stderr, re.MULTILINE)
        raise AssertionError("acceptance-command-failed: " + str(argv[0]) +
                             " rc=" + str(result.returncode) + " code=" + code +
                             (" causes=" + causes.group(1) if causes else ""))
    return result.stdout


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def network_state(prefix=()):
    """Capture both address families' routes and policy rules."""
    return {(family, kind): command([*prefix, "ip", "-j", family, kind, "show",
                                    *(["table", "all"] if kind == "route" else [])])
            for family in ("-4", "-6") for kind in ("route", "rule")}


@contextmanager
def provision_system_cli_bin():
    """Administer exactly one disposable-VM fixture directory, then restore it.

    The hosted image deliberately makes this directory world writable:
    https://github.com/actions/runner-images/blob/main/images/ubuntu/scripts/build/install-nodejs.sh
    Production installation correctly refuses that state. Never change its
    trust rules or recursively change the image's existing tool files.
    """
    if (os.geteuid() != 0 or os.environ.get("MIHOMO_V1_DISPOSABLE_VM") != "1"
            or os.environ.get("MIHOMO_V1_PRIVILEGED") != "1"):
        raise RuntimeError("disposable-root-system-cli-fixture-required")
    target = "/usr/local/bin"
    for parent in ("/", "/usr", "/usr/local"):
        info = os.lstat(parent)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022):
            raise RuntimeError("unsafe-system-cli-fixture-ancestor")
    original = os.lstat(target)
    if not stat.S_ISDIR(original.st_mode):
        raise RuntimeError("system-cli-fixture-must-be-real-directory")
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        identity = (original.st_dev, original.st_ino)
        if (opened.st_dev, opened.st_ino) != identity:
            raise RuntimeError("system-cli-fixture-directory-changed")
        evidence = {"path": target, "original_uid": original.st_uid,
                    "original_gid": original.st_gid, "original_mode": oct(stat.S_IMODE(original.st_mode)),
                    "restored": False}
        try:
            os.fchown(descriptor, 0, 0)
            os.fchmod(descriptor, 0o755)
            yield evidence
        finally:
            # Restore through the opened directory, never through a replaced
            # name or a symlink. chown may clear mode bits, so restore mode last.
            os.fchown(descriptor, original.st_uid, original.st_gid)
            os.fchmod(descriptor, stat.S_IMODE(original.st_mode))
            restored = os.fstat(descriptor)
            if (restored.st_uid, restored.st_gid, stat.S_IMODE(restored.st_mode)) != (
                    original.st_uid, original.st_gid, stat.S_IMODE(original.st_mode)):
                raise RuntimeError("system-cli-fixture-metadata-restore-failed")
            current = os.lstat(target)
            if (current.st_dev, current.st_ino) != identity:
                raise RuntimeError("system-cli-fixture-directory-changed")
            evidence["restored"] = True
    finally:
        os.close(descriptor)


class FixtureProvisioningTests(unittest.TestCase):
    """Real chmod/finally checks redirected to a private directory; no system writes."""
    def test_provision_refuses_missing_disposable_permission(self):
        with patch.dict(os.environ, {"MIHOMO_V1_DISPOSABLE_VM": "0"}), \
                patch("os.open", side_effect=AssertionError("unexpected directory open")):
            with self.assertRaisesRegex(RuntimeError, "disposable-root"):
                with provision_system_cli_bin():
                    self.fail("unsafe fixture entered")

    def exercise(self, body_fails=False, kind="directory"):
        with tempfile.TemporaryDirectory(prefix="mihomoctl-bin-fixture-test-") as folder:
            directory = Path(folder) / "bin"
            directory.mkdir(mode=0o777)
            directory.chmod(0o777)
            if kind == "symlink":
                fake_target = Path(folder) / "link"
                fake_target.symlink_to(directory, target_is_directory=True)
            elif kind == "file":
                fake_target = Path(folder) / "file"
                fake_target.write_text("fixture", encoding="utf-8")
            else:
                fake_target = directory
            original = fake_target.lstat()
            real_lstat, real_open = os.lstat, os.open
            def lstat(path, *args, **kwargs):
                if str(path) == "/usr/local/bin":
                    return real_lstat(fake_target)
                if str(path) in ("/", "/usr", "/usr/local"):
                    values = list(real_lstat(folder))
                    values[0], values[4], values[5] = stat.S_IFDIR | 0o755, 0, 0
                    return os.stat_result(values)
                return real_lstat(path, *args, **kwargs)
            def open_directory(path, flags):
                self.assertEqual(path, "/usr/local/bin")
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertTrue(flags & os.O_DIRECTORY)
                return real_open(directory, flags)
            with patch.dict(os.environ, {"MIHOMO_V1_DISPOSABLE_VM": "1", "MIHOMO_V1_PRIVILEGED": "1"}), \
                    patch("os.geteuid", return_value=0), patch("os.lstat", side_effect=lstat), \
                    patch("os.open", side_effect=open_directory) as opened, patch("os.fchown") as ownership:
                if kind != "directory":
                    with self.assertRaisesRegex(RuntimeError, "must-be-real-directory"):
                        with provision_system_cli_bin():
                            self.fail("unsafe target entered")
                    opened.assert_not_called()
                    ownership.assert_not_called()
                    return
                def run():
                    with provision_system_cli_bin() as evidence:
                        self.assertEqual(stat.S_IMODE(real_lstat(directory).st_mode), 0o755)
                        if body_fails:
                            raise ValueError("fixture body failed")
                    return evidence
                if body_fails:
                    with self.assertRaisesRegex(ValueError, "fixture body failed"):
                        run()
                else:
                    self.assertTrue(run()["restored"])
                self.assertEqual(stat.S_IMODE(real_lstat(directory).st_mode), 0o777)
                self.assertEqual(ownership.call_args_list[0].args[1:], (0, 0))
                self.assertEqual(ownership.call_args_list[-1].args[1:], (original.st_uid, original.st_gid))

    def test_provision_restores_original_metadata(self):
        self.exercise()

    def test_provision_restores_metadata_when_body_fails(self):
        self.exercise(body_fails=True)

    def test_provision_refuses_symlink_and_regular_file(self):
        for kind in ("symlink", "file"):
            with self.subTest(kind=kind):
                self.exercise(kind=kind)


@unittest.skipUnless(ENABLED, "explicit disposable Ubuntu VM acceptance")
class PrivilegedAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if (os.geteuid() != 0 or os.environ.get("MIHOMO_V1_DISPOSABLE_VM") != "1"
                or not Path("/run/systemd/system").is_dir()):
            raise RuntimeError("disposable-root-systemd-vm-required")
        for executable in ("systemctl", "loginctl", "useradd", "userdel", "runuser", "ip"):
            if not shutil.which(executable):
                raise RuntimeError("acceptance-tool-missing: " + executable)
        if Path("/etc/mihomoctl").exists() or Path("/etc/systemd/system/mihomoctl.service").exists():
            raise RuntimeError("refuse-to-touch-existing-system-installation")
        cls.python = Path(os.environ["MIHOMO_V1_PYTHON"])
        cls.core = Path(os.environ["MIHOMO_TEST_CORE"])
        cls.source = Path(os.environ["MIHOMO_V1_SOURCE"])
        cls.base = Path(os.environ["MIHOMO_V1_FIXTURE"])
        cls.accounts = []
        cls.user_sessions = set()
        cls.namespace = "mucv1-" + str(os.getpid())
        cls.system_installed = False
        cls.namespace_created = False
        cls.ports = {}
        for suffix in ("a", "b"):
            name = "mucv1" + str(os.getpid()) + suffix
            home = cls.base / name
            # Own the fixture HOME explicitly: copying the image's skel and
            # initializing its global login logs are unrelated to acceptance.
            command(["useradd", "--no-create-home", "--no-log-init", "--user-group",
                     "--home-dir", home, "--shell", "/bin/bash", name], timeout=180)
            account = pwd.getpwnam(name)
            home.mkdir(mode=0o700)
            os.chown(home, account.pw_uid, account.pw_gid)
            runtime = home / ".runtime"
            runtime.mkdir(mode=0o700)
            os.chown(runtime, account.pw_uid, account.pw_gid)
            cls.accounts.append((name, account.pw_uid, home))
            cls.ports[name] = port()
        cls.network_before = network_state()
        class Target(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(204)
                self.end_headers()
            do_GET = do_HEAD
            def log_message(self, *args):
                pass
        cls.target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        cls.target_thread = threading.Thread(target=cls.target.serve_forever, daemon=True)
        cls.target_thread.start()
        cls.shell_before = {}
        for account in cls.accounts:
            name, uid, home = account
            for shell_file in (".bashrc", ".profile", ".zshrc"):
                p = home / shell_file
                if not p.exists():
                    p.write_text("# acceptance-owned startup file\n", encoding="utf-8")
                    os.chown(p, uid, pwd.getpwuid(uid).pw_gid)
                cls.shell_before[(name, shell_file)] = p.read_bytes()
            cls.cli(account, "init", "--core", cls.core, "--port", cls.ports[name])

    @classmethod
    def env(cls, account):
        name, uid, home = account
        runtime = "/run/user/" + str(uid) if uid in cls.user_sessions else str(home / ".runtime")
        return {"HOME": str(home), "USER": name, "LOGNAME": name,
                "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_RUNTIME_DIR": runtime,
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + runtime + "/bus"}

    @classmethod
    def cli(cls, account, *args, expected=0, namespace=False):
        if account:
            envargs = [k + "=" + v for k, v in cls.env(account).items()]
            argv = ["runuser", "-u", account[0], "--", "env", "-i", *envargs,
                    str(cls.python), "-m", "mihomoctl"]
            cwd = account[2]
        else:
            argv = [str(cls.python), "-m", "mihomoctl", "--system"]
            cwd = cls.base
        if namespace:
            argv = ["ip", "netns", "exec", cls.namespace, *argv]
        result = subprocess.run([str(a) for a in [*argv, *args, "--json"]], cwd=cwd,
                                capture_output=True, text=True, timeout=90)
        if result.returncode != expected:
            # Error codes only; never echo stdout that may contain credentials.
            try:
                errors = json.loads(result.stdout).get("errors", [])
                codes = [e.get("code", "unknown") for e in errors if isinstance(e, dict)]
            except ValueError:
                codes = ["invalid-json-response"]
            raise AssertionError("CLI " + str(args[0]) + " rc=" + str(result.returncode)
                                 + " expected=" + str(expected) + " codes=" + repr(codes))
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise AssertionError("CLI did not return one JSON object") from None
        if value.get("schema") != "mihomoctl/v1":
            raise AssertionError("wrong-json-schema")
        return value

    @classmethod
    def wait_cli(cls, account, *args, namespace=False, timeout=20):
        """A new MainPID precedes listener readiness; require observed recovery."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return cls.cli(account, *args, namespace=namespace)
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)

    @classmethod
    def user_systemctl(cls, account, *args):
        envargs = [k + "=" + v for k, v in cls.env(account).items()]
        return command(["runuser", "-u", account[0], "--", "env", "-i", *envargs,
                        "systemctl", "--user", *args])

    def check_shells(self):
        for name, uid, home in self.accounts:
            for filename in (".bashrc", ".zshrc", ".profile"):
                self.assertTrue((home / filename).read_bytes() == self.shell_before[(name, filename)],
                                "shell-startup-file-changed")

    def test_10_user_process_and_isolation(self):
        alice, bob = self.accounts
        for account in self.accounts:
            value = self.cli(account, "start")
            self.assertEqual(value["overall"], "PASS")
            self.cli(account, "status")
            self.cli(account, "restart")
            self.cli(account, "config", "validate")
            self.cli(account, "tun", "enable", expected=2)
            # --system is before the subcommand in the public grammar.
            envargs = [k + "=" + v for k, v in self.env(account).items()]
            result = subprocess.run(["runuser", "-u", account[0], "--", "env", "-i", *envargs,
                                     str(self.python), "-m", "mihomoctl", "--system", "service", "install", "--json"],
                                    cwd=account[2], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 2, "non-root-system-mutation-permitted")
            exported = account[2] / "proxy.env"
            self.cli(account, "env", "export", "--output", exported)
            self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
            self.assertTrue("HTTP_PROXY=" in exported.read_text(), "missing-http-proxy")
            entries = {line.split("=", 1)[0]: shlex.split(line.split("=", 1)[1])[0]
                       for line in exported.read_text().splitlines()
                       if "=" in line and not line.startswith("#")}
            endpoint = urlsplit(entries["HTTP_PROXY"])
            target = "http://127.0.0.1:" + str(self.target.server_port) + "/"
            for authenticated in (False, True):
                headers = {}
                if authenticated:
                    credential = unquote(endpoint.username or "") + ":" + unquote(endpoint.password or "")
                    headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credential.encode()).decode()
                conn = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=5)
                try:
                    conn.request("HEAD", target, headers=headers)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 204 if authenticated else 407,
                                     "real-http-proxy-authentication-failed")
                    response.read()
                finally:
                    conn.close()
            dump = account[2] / "exec-env.json"
            worker = "import json,os,pathlib;pathlib.Path(os.environ['HOME'],'exec-env.json').write_text(json.dumps({k:os.environ.get(k) for k in " + repr(PROXY_KEYS) + "}));raise SystemExit(17)"
            envargs = [k + "=" + v for k, v in self.env(account).items()]
            result = subprocess.run(["runuser", "-u", account[0], "--", "env", "-i", *envargs,
                                     str(self.python), "-m", "mihomoctl", "exec", "--",
                                     str(self.python), "-c", worker], cwd=account[2], capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 17, "exec-did-not-pass-child-exit-code")
            inherited = json.loads(dump.read_text())
            self.assertTrue(all(inherited[k] for k in PROXY_KEYS), "proxy-inheritance-incomplete")
            dump.unlink()
        # A second real UID cannot read either configuration or exported secrets.
        result = subprocess.run(["runuser", "-u", bob[0], "--", "cat", str(alice[2] / "proxy.env")],
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, "cross-uid-secret-read-permitted")
        self.check_shells()
        self.assertTrue(network_state() == self.network_before,
                        "user-mode-changed-system-routes")
        for account in self.accounts:
            self.cli(account, "stop")
            self.cli(account, "status", expected=1)

    def test_20_real_user_systemd_and_environment_binding(self):
        import yaml
        account = self.accounts[0]
        name, uid, home = account
        command(["loginctl", "enable-linger", name])  # Test fixture administration only.
        command(["systemctl", "start", "user@" + str(uid) + ".service"])
        self.user_sessions.add(uid)
        self.user_systemctl(account, "show-environment")
        self.cli(account, "service", "install")
        self.assertEqual(command(["runuser", "-u", name, "--", "env",
                                  "XDG_RUNTIME_DIR=/run/user/" + str(uid),
                                  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + str(uid) + "/bus",
                                  "systemctl", "--user", "is-active", "mihomoctl.service"], allowed=(3,)).strip(), "inactive")
        for action in ("start", "restart"):
            self.cli(account, "service", action)
        unitdir = home / ".config/systemd/user"
        unitdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        unit = unitdir / "mihomoctl-test-worker.service"
        worker = self.base / "env-worker.py"
        worker.write_text("import json,os,pathlib,time\n"
                          "p=pathlib.Path(os.environ['HOME'])/'service-env.json'\n"
                          "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)\n"
                          "os.write(fd,json.dumps({k:os.environ.get(k) for k in " + repr(PROXY_KEYS) + "}).encode());os.close(fd)\n"
                          "time.sleep(120)\n", encoding="utf-8")
        worker.chmod(0o644)
        unit.write_text("[Unit]\nDescription=Disposable environment inheritance fixture\n"
                        "[Service]\nType=simple\nExecStart=" + str(self.python) + " " + str(worker) + "\n",
                        encoding="utf-8")
        os.chown(unit, uid, pwd.getpwuid(uid).pw_gid)
        unit.chmod(0o600)
        manager = home / ".config/mihomoctl/manager.yaml"
        data = yaml.safe_load(manager.read_text())
        data.setdefault("bindings", {})["worker"] = {"profile": "default", "adapter": "systemd",
                                                      "target": "mihomoctl-test-worker.service"}
        manager.write_text(yaml.safe_dump(data), encoding="utf-8")
        manager.chmod(0o600)
        self.cli(account, "integration", "install", "worker")
        from mihomoctl.integration.systemd_adapter import DROPIN_NAME
        expected_dropin = unitdir / (unit.name + ".d") / DROPIN_NAME
        loaded_dropins = self.user_systemctl(account, "show", unit.name, "-p", "DropInPaths", "--value")
        self.assertIn(str(expected_dropin), loaded_dropins.split(),
                      "integration-dropin-not-loaded-by-user-manager")
        expected_envfile = home / ".config/mihomoctl/integration/worker.env"
        loaded_envfiles = self.user_systemctl(account, "show", unit.name, "-p", "EnvironmentFiles", "--value")
        self.assertIn(str(expected_envfile), loaded_envfiles,
                      "integration-environment-file-not-loaded-by-user-manager")
        expected_environment = dict(line.split("=", 1) for line in expected_envfile.read_text().splitlines()
                                    if "=" in line and not line.startswith("#"))
        self.assertEqual(set(expected_environment), set(PROXY_KEYS),
                         "integration-environment-file-key-inventory-mismatch")
        unset = self.user_systemctl(account, "show", unit.name, "-p", "UnsetEnvironment", "--value")
        unset_proxy_keys = sorted(set(unset.split()) & set(PROXY_KEYS))
        self.assertFalse(unset_proxy_keys, "worker-unsets-proxy-keys: " + ",".join(unset_proxy_keys))
        # Product integration must not start the consuming service.
        result = subprocess.run(["runuser", "-u", name, "--", "env",
                                 "XDG_RUNTIME_DIR=/run/user/" + str(uid),
                                 "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + str(uid) + "/bus",
                                 "systemctl", "--user", "is-active", unit.name], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, "integration-started-third-party-service")
        self.user_systemctl(account, "start", unit.name)  # Operator action, not product action.
        dump = home / "service-env.json"
        for _ in range(100):
            if dump.exists():
                break
            time.sleep(.1)
        self.assertTrue(dump.exists(), "noninteractive-worker-did-not-start")
        inherited = json.loads(dump.read_text())
        missing = [key for key in PROXY_KEYS if not inherited.get(key)]
        # Names from this fixed vocabulary are safe diagnostics; never dump values.
        self.assertFalse(missing, "systemd-env-inheritance-incomplete: " + ",".join(missing))
        self.assertTrue(inherited == expected_environment, "systemd-environment-values-differ")
        self.user_systemctl(account, "stop", unit.name)
        dump.unlink()
        self.cli(account, "integration", "remove", "worker")
        self.cli(account, "service", "stop")
        self.check_shells()

    def test_30_real_system_service_and_crash_recovery(self):
        self.cli(None, "init", "--core", self.core, "--port", port())
        self.cli(None, "service", "install")
        self.__class__.system_installed = True
        self.cli(None, "service", "start")
        self.cli(None, "service", "restart")
        pid = int(command(["systemctl", "show", "mihomoctl.service", "-p", "MainPID", "--value"]).strip())
        self.assertNotEqual(pwd.getpwnam("mihomoctl").pw_uid, 0)
        self.assertTrue(Path("/proc/" + str(pid)).stat().st_uid == pwd.getpwnam("mihomoctl").pw_uid,
                        "system-core-ran-as-root")
        command(["systemctl", "kill", "--signal=SIGKILL", "--kill-who=main", "mihomoctl.service"])
        replacement = 0
        for _ in range(100):
            text = command(["systemctl", "show", "mihomoctl.service", "-p", "MainPID", "--value"]).strip()
            replacement = int(text or "0")
            if replacement and replacement != pid:
                break
            time.sleep(.2)
        self.assertTrue(replacement not in (0, pid), "systemd-crash-recovery-failed")
        self.wait_cli(None, "status")
        self.cli(None, "service", "stop")

    def test_40_tun_in_isolated_network_namespace(self):
        if not self.system_installed:
            self.fail("system-service-acceptance-required-before-tun")
        if not Path("/dev/net/tun").exists():
            self.fail("mandatory-tun-device-unavailable")
        command(["ip", "netns", "add", self.namespace])
        self.__class__.namespace_created = True
        ns = ["ip", "netns", "exec", self.namespace]
        command([*ns, "ip", "link", "set", "lo", "up"])
        command([*ns, "ip", "link", "add", "uplink", "type", "dummy"])
        command([*ns, "ip", "addr", "add", "192.0.2.1/24", "dev", "uplink"])
        command([*ns, "ip", "link", "set", "uplink", "up"])
        command([*ns, "ip", "route", "add", "default", "dev", "uplink"])
        before = network_state(ns)
        from mihomoctl.lifecycle.systemd import NAMESPACE_DROPIN, namespace_dropin_text
        dropin = Path("/etc/systemd/system/mihomoctl.service.d") / NAMESPACE_DROPIN
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(namespace_dropin_text("/run/netns/" + self.namespace), encoding="utf-8")
        dropin.chmod(0o644)
        command(["systemctl", "daemon-reload"])
        self.cli(None, "service", "start", namespace=True)
        self.cli(None, "tun", "enable", namespace=True)
        links = json.loads(command([*ns, "ip", "-j", "-d", "link", "show"]))
        self.assertTrue(any(p.get("linkinfo", {}).get("info_kind") == "tun" for p in links),
                        "tun-command-did-not-create-device")
        self.assertTrue(network_state(ns) != before, "tun-did-not-install-transparent-routing")
        caps = command(["systemctl", "show", "mihomoctl.service", "-p", "AmbientCapabilities", "--value"])
        self.assertIn("cap_net_admin", caps.lower())
        # Both operator restarts and systemd crash recovery recreate ephemeral
        # devices. Authorization must follow proven core ownership, not a stale
        # interface index, while preserving refusal of foreign same-name devices.
        self.cli(None, "restart", namespace=True)
        self.cli(None, "tun", "status", namespace=True)
        pid = int(command(["systemctl", "show", "mihomoctl.service", "-p", "MainPID", "--value"]).strip())
        command(["systemctl", "kill", "--signal=SIGKILL", "--kill-who=main", "mihomoctl.service"])
        replacement = 0
        for _ in range(100):
            replacement = int(command(["systemctl", "show", "mihomoctl.service", "-p", "MainPID", "--value"]).strip() or "0")
            if replacement and replacement != pid:
                break
            time.sleep(.2)
        self.assertTrue(replacement not in (0, pid), "tun-systemd-crash-recovery-failed")
        self.wait_cli(None, "status", namespace=True)
        self.wait_cli(None, "tun", "status", namespace=True)
        self.cli(None, "tun", "disable", namespace=True)
        links = json.loads(command([*ns, "ip", "-j", "-d", "link", "show"]))
        self.assertFalse(any(p.get("linkinfo", {}).get("info_kind") == "tun" for p in links),
                         "tun-disable-left-device")
        self.assertTrue(network_state(ns) == before,
                        "tun-disable-did-not-restore-namespace-routes")
        self.cli(None, "service", "stop", namespace=True)
        self.assertTrue(network_state() == self.network_before,
                        "isolated-tun-test-changed-host-routes")

    def test_45_tun_refuses_foreign_device_and_preserves_active_generation(self):
        import yaml
        if not self.namespace_created:
            self.fail("isolated-network-namespace-required")
        ns = ["ip", "netns", "exec", self.namespace]
        manager_path = Path("/etc/mihomoctl/manager.yaml")
        manager = yaml.safe_load(manager_path.read_text())
        config_path = Path(manager["core"]["config"])
        device = manager.get("tun", {}).get("device", "mihomo0")
        self.cli(None, "service", "start", namespace=True)
        previous = {p: p.read_bytes() for p in (manager_path, config_path)}
        cap_file = Path("/etc/systemd/system/mihomoctl.service.d/50-mihomoctl-tun.conf")
        cap_before = cap_file.read_bytes() if cap_file.exists() else None
        command([*ns, "ip", "tuntap", "add", "dev", device, "mode", "tun"])
        try:
            before_link = json.loads(command([*ns, "ip", "-j", "link", "show", "dev", device]))[0]["ifindex"]
            routes = network_state(ns)
            result = subprocess.run([*ns, str(self.python), "-m", "mihomoctl", "--system", "tun", "enable", "--json"],
                                    cwd=self.base, capture_output=True, text=True, timeout=90)
            self.assertIn(result.returncode, (1, 2), "tun-claimed-an-existing-foreign-device")
            self.assertNotEqual(json.loads(result.stdout)["overall"], "PASS")
            after_link = json.loads(command([*ns, "ip", "-j", "link", "show", "dev", device]))[0]["ifindex"]
            self.assertEqual(after_link, before_link, "foreign-device-was-replaced")
            for path, body in previous.items():
                self.assertTrue(path.read_bytes() == body, "failed-tun-enable-changed-active-config")
            self.assertTrue((cap_file.read_bytes() if cap_file.exists() else None) == cap_before,
                            "failed-tun-enable-changed-capabilities")
            self.assertTrue(network_state(ns) == routes,
                            "failed-tun-enable-changed-routes")
            self.cli(None, "status", namespace=True)
        finally:
            command([*ns, "ip", "link", "delete", "dev", device])
            self.cli(None, "service", "stop", namespace=True)

    def test_60_system_cli_install_is_readable_by_users_and_preserves_runtime(self):
        import yaml
        manager_path = Path("/etc/mihomoctl/manager.yaml")
        manager = yaml.safe_load(manager_path.read_text())
        config_path = Path(manager["core"]["config"])
        previous = {p: p.read_bytes() for p in (manager_path, config_path)}
        bootstrap = self.source / "scripts/bootstrap.py"
        with provision_system_cli_bin() as fixture:
            installed = False
            try:
                command([self.python, bootstrap, "install", "--system", "--source", self.source,
                         "--wheelhouse", os.environ["MIHOMO_V1_WHEELHOUSE"],
                         "--python", "/usr/bin/python3"], timeout=180)
                installed = True
                for account in self.accounts:
                    envargs = [k + "=" + v for k, v in self.env(account).items()]
                    result = command(["runuser", "-u", account[0], "--", "env", "-i", *envargs,
                                      "/usr/local/bin/mihomoctl", "version", "--json"], cwd=account[2])
                    self.assertEqual(json.loads(result)["data"]["mihomoctl"], REPOSITORY_VERSION)
                for path, body in previous.items():
                    self.assertTrue(path.read_bytes() == body, "cli-install-changed-core-configuration")
            finally:
                if installed:
                    command([self.python, bootstrap, "uninstall", "--system"], timeout=180)
        self.assertTrue(fixture["restored"], "system-cli-fixture-metadata-not-restored")
        type(self).system_cli_bin_fixture = fixture
        for path, body in previous.items():
            self.assertTrue(path.read_bytes() == body, "cli-uninstall-removed-core-configuration")
        self.check_shells()
        self.assertTrue(network_state() == self.network_before,
                        "cli-installation-changed-host-network")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "target"):
            cls.target.shutdown()
            cls.target.server_close()
        if cls.system_installed:
            subprocess.run(["systemctl", "stop", "mihomoctl.service"], capture_output=True, timeout=30)
        for name, uid, home in cls.accounts:
            # Only accounts created by this fixture are eligible for cleanup.
            if not name.startswith("mucv1" + str(os.getpid())) or home.parent != cls.base:
                raise RuntimeError("unsafe-acceptance-cleanup-target")
            subprocess.run(["loginctl", "disable-linger", name], capture_output=True, timeout=30)
            subprocess.run(["loginctl", "terminate-user", name], capture_output=True, timeout=30)
            subprocess.run(["userdel", "--remove", name], capture_output=True, timeout=30)
        if cls.namespace_created:
            subprocess.run(["ip", "netns", "delete", cls.namespace], capture_output=True, timeout=30)


if __name__ == "__main__":
    if not ENABLED:
        raise SystemExit("mandatory acceptance not enabled; refusing a skipped success")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PrivilegedAcceptance)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "success": result.wasSuccessful() and not result.skipped,
              "platform": sys.platform, "real_uids": True, "systemd": True, "tun": True}
    report.update(json.loads(os.environ.get("MIHOMO_V1_SOURCE_EVIDENCE", "{}")))
    if hasattr(PrivilegedAcceptance, "system_cli_bin_fixture"):
        report["system_cli_bin_fixture"] = PrivilegedAcceptance.system_cli_bin_fixture
    if os.environ.get("MIHOMO_V1_REPORT"):
        Path(os.environ["MIHOMO_V1_REPORT"]).write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    raise SystemExit(0 if report["success"] and result.testsRun >= 6 else 1)
