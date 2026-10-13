"""V1 UX contract tests: the console/TUI surface, not the domain implementation.

These assert what the interface layer promises:
  * the console never re-enters the Bash CLI and never decides a verdict;
  * a missing Application yields an explicit UNVERIFIED document, never a
    silent success;
  * the runtime view always carries the seven V1 facts;
  * the console renders ProxyProfile separately from the subscription page;
  * the retained subscription identifier still routes to the subscription page;
  * no TUI or console code names a third-party daemon lifecycle verb.

Run on Linux:  python3 -m unittest tests.test_v1_ux
"""
import ast
import contextlib
import io
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The retained runtime modules are Linux-only (fcntl, procfs). Static contract
# checks below still run anywhere; the service-level suites skip when the module
# cannot be imported so a non-Linux host reports skips instead of false failures.
try:
    from mihomoctl.controller import controller_service as service_module
    from mihomoctl.controller.controller_service import ConsoleService
    from mihomoctl.controller.controller_types import ControlError
    SERVICE_IMPORT_ERROR = None
except (ImportError, OSError, ValueError) as error:  # pragma: no cover - platform gate
    service_module = None
    ConsoleService = None
    ControlError = None
    SERVICE_IMPORT_ERROR = error

requires_service = unittest.skipIf(
    ConsoleService is None, "runtime modules require Linux: " + str(SERVICE_IMPORT_ERROR))

RUNTIME_FIELDS = ("core", "controller", "listeners", "config", "proxy_mode", "tun", "error")

# Pure argv construction: importable on every platform, no runtime probe.
from mihomoctl.bridge import bridge_forward


class FakeContext(dict):
    """A stand-in for Application.context; attribute access must also work."""


class FakeApplication:
    """Minimal Application honouring the frozen facade only.

    Deliberately records calls so a test can prove the console asks the domain
    instead of running anything itself.
    """

    def __init__(self, system=False, status=None, checks=None, profiles=None, context=None):
        self.system = system
        self.context = context if context is not None else FakeContext()
        self.calls = []
        self._status = status
        self._checks = checks
        self._profiles = profiles

    def status(self):
        self.calls.append(("status",))
        return dict(self._status or {})

    def health(self, profile=None, egress_url=None):
        self.calls.append(("health", profile, egress_url))
        return list(self._checks or [])

    def lifecycle(self, action):
        self.calls.append(("lifecycle", action))
        return {"overall": "PASS", "action": action, "state": "confirmed"}

    def profiles(self):
        self.calls.append(("profiles",))
        return dict(self._profiles or {})


@requires_service
class NoAppConsoleTests(unittest.TestCase):
    """Without an Application every answer is explicit, never invented."""

    def setUp(self):
        self.service = ConsoleService(Path("/nonexistent/mihomo-config.yaml"))

    def test_status_without_application_is_unverified_with_all_seven_fields(self):
        document = self.service.runtime_document()
        self.assertEqual(document["overall"], "UNVERIFIED")
        self.assertEqual(document["reason"], service_module.UNVERIFIED_REASON)
        for name in RUNTIME_FIELDS:
            self.assertIn(name, document, name)

    def test_health_without_application_is_unverified_not_empty_pass(self):
        document = self.service.health_document()
        self.assertEqual(document["overall"], "UNVERIFIED")
        self.assertEqual(document["checks"], [])
        self.assertTrue(document["limits"], "fixed evidence boundaries must always ship")

    def test_profiles_without_application_is_unverified(self):
        document = self.service.profiles_document()
        self.assertEqual(document["overall"], "UNVERIFIED")
        self.assertEqual(document["profiles"], [])

    def test_lifecycle_without_application_reports_changed_false(self):
        for action in ("start", "stop", "restart"):
            with self.subTest(action=action):
                result = self.service.lifecycle(action)
                self.assertEqual(result["overall"], "UNVERIFIED")
                self.assertEqual(result["state"], service_module.UNVERIFIED_REASON)
                self.assertIs(result["changed"], False)

    def test_console_never_returns_a_guessed_success_for_lifecycle(self):
        for action in ("start", "stop", "restart"):
            with self.subTest(action=action):
                document = self.service.shell(action)
                self.assertNotEqual(document.get("state"), "confirmed")


@requires_service
class ApplicationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.config = Path(tempfile.mkdtemp()) / "config.yaml"
        self.config.write_text("proxies: []\n", encoding="utf-8")

    def service(self, app):
        return ConsoleService(self.config, app=app)

    def test_status_is_projected_onto_the_fixed_contract(self):
        app = FakeApplication(status={
            "scope": "user", "backend": "process", "overall": "PASS", "evidence": "confirmed",
            "core": {"path": "/opt/mihomo", "version": "v1.19.32"},
            "controller": {"state": "connected", "endpoint": "127.0.0.1:9090"},
            "listeners": [{"kind": "mixed", "endpoint": "127.0.0.1:28443"}],
            "config": {"path": "/config/mihomo/config.yaml", "active": True},
            "proxy_mode": "rule", "tun": {"state": "disabled"}, "error": None})
        document = self.service(app).runtime_document()
        self.assertEqual(document["overall"], "PASS")
        self.assertEqual(document["proxy_mode"], "rule")
        self.assertEqual(document["listeners"][0]["endpoint"], "127.0.0.1:28443")
        self.assertEqual(document["tun"]["state"], "disabled")
        self.assertNotIn("running", document["core"])
        self.assertIn(("status",), app.calls)

    def test_missing_facts_render_as_unknown_never_as_a_healthy_default(self):
        document = self.service(FakeApplication(status={})).runtime_document()
        self.assertEqual(document["overall"], "UNVERIFIED")
        for name in RUNTIME_FIELDS:
            self.assertIn(name, document, name)
        self.assertEqual(document["proxy_mode"], "unknown")
        self.assertEqual(document["tun"]["state"], "unknown")
        self.assertIsNone(document["error"])

    def test_unknown_enumerations_are_rejected_not_forwarded(self):
        document = self.service(FakeApplication(status={"overall": "GREAT", "evidence": "vibes"})).runtime_document()
        self.assertEqual(document["overall"], "UNVERIFIED")
        self.assertEqual(document["evidence"], "inferred")

    def test_scope_follows_the_injected_application(self):
        self.assertEqual(self.service(FakeApplication(system=True)).scope(), "system")
        self.assertEqual(self.service(FakeApplication(system=False)).scope(), "user")
        self.assertEqual(ConsoleService(self.config).scope(), "user")

    def test_health_normalizes_every_status_and_evidence_value(self):
        app = FakeApplication(checks=[
            {"name": "listener", "status": "PASS", "evidence": "confirmed"},
            {"name": "egress", "status": "maybe", "evidence": "vibes"},
            "not-a-row"])
        document = self.service(app).health_document()
        self.assertEqual([row["status"] for row in document["checks"]], ["PASS", "UNVERIFIED"])
        self.assertEqual([row["evidence"] for row in document["checks"]], ["confirmed", "unavailable"])
        self.assertEqual(len(document["checks"]), 2, "a malformed row must not be rendered")
        self.assertIn(("health", None, None), app.calls)

    def test_health_forwards_profile_and_egress_without_guessing(self):
        app = FakeApplication(checks=[])
        self.service(app).health_document(profile="work", egress_url="https://example.com/")
        self.assertIn(("health", "work", "https://example.com/"), app.calls)

    def test_health_tolerates_an_application_without_keyword_support(self):
        class Legacy(FakeApplication):
            def health(self):
                return []
        self.assertEqual(self.service(Legacy()).health_document()["checks"], [])

    def test_profiles_are_redacted_projections_with_bindings(self):
        app = FakeApplication(
            profiles={"default": {"name": "default", "listeners": ["mixed"], "no_proxy": ["127.0.0.1"]}},
            context=FakeContext(default_profile="default",
                                bindings={"worker": {"adapter": "systemd", "profile": "default",
                                                     "target": "worker.service"}}))
        document = self.service(app).profiles_document()
        self.assertEqual(document["selected"], "default")
        self.assertEqual(document["profiles"][0]["credentials"], "external-private-file")
        self.assertEqual(document["bindings"]["worker"]["adapter"], "systemd")
        self.assertTrue(document["environment"])

    def test_lifecycle_asks_the_domain_and_keeps_the_shell_unchanged(self):
        app = FakeApplication()
        result = self.service(app).lifecycle("restart")
        self.assertEqual(result["action"], "restart")
        self.assertEqual(result["shell"], "unchanged")
        self.assertIn(("lifecycle", "restart"), app.calls)

    def test_lifecycle_rejects_actions_outside_the_managed_runtime(self):
        with self.assertRaises(ControlError):
            self.service(FakeApplication()).lifecycle("reload")

    def test_domain_errors_remain_safe_console_errors(self):
        from mihomoctl.errors import ConfigError
        app = FakeApplication()
        app.status = mock.Mock(side_effect=ConfigError("config-invalid", "private-value"))
        app.health = mock.Mock(side_effect=ConfigError("config-invalid", "private-value"))
        app.profiles = mock.Mock(side_effect=ConfigError("config-invalid", "private-value"))
        app.lifecycle = mock.Mock(side_effect=ConfigError("config-invalid", "private-value"))
        console = self.service(app)
        for document in (console.runtime_document(), console.health_document(), console.profiles_document()):
            self.assertEqual(document["overall"], "UNVERIFIED")
            self.assertEqual(document["reason"], "config-invalid")
            self.assertNotIn("private-value", json.dumps(document))
        with self.assertRaises(ControlError) as raised:
            console.lifecycle("start")
        self.assertEqual(str(raised.exception), "config-invalid")

    def test_worker_context_is_restored_after_domain_failure(self):
        from concurrent.futures import ThreadPoolExecutor
        from mihomoctl.controller.controller_transaction import runtime_application
        app = FakeApplication()
        console = self.service(app)
        def preview(*args, **kwargs):
            self.assertIs(runtime_application.get(), app)
            raise ControlError("preview-failed")
        def worker():
            self.assertIsNone(runtime_application.get())
            with self.assertRaises(ControlError):
                console.policy()
            self.assertIsNone(runtime_application.get())
        with mock.patch("mihomoctl.controller.controller_policy.policy_candidate", side_effect=preview):
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(worker).result()


@requires_service
class RealApplicationBridgeTests(unittest.TestCase):
    """Read actual managed files through the facade, without starting a core."""

    def setUp(self):
        from mihomoctl.app import Application
        from mihomoctl.config import (Binding, CoreSettings, Manager, Profile,
                                      compose_core_config, render_manager)
        from mihomoctl.credentials import Credentials
        self.folder = tempfile.TemporaryDirectory(prefix="mihomoctl-ui-contract-")
        self.addCleanup(self.folder.cleanup)
        home = Path(self.folder.name)
        environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                       "XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state"),
                       "XDG_CACHE_HOME": str(home / "cache"), "XDG_RUNTIME_DIR": ""}
        self.patch = mock.patch.dict(os.environ, environment)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app = Application()
        scope = self.app.scope
        for directory in (scope.config_root, scope.credentials_dir, scope.state_root):
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            directory.chmod(0o700)
        credentials = scope.credentials_dir / "work.yaml"
        Credentials.create(credentials, "test-user", "private-password")
        core_config = scope.config_root / "config.yaml"
        def free_port():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                return listener.getsockname()[1]
        core_config.write_text(compose_core_config(free_port(), "test-user", "private-password",
                                                   free_port(), "private-controller-token-for-ui-fixture"), encoding="utf-8")
        core_config.chmod(0o600)
        manager = Manager(core=CoreSettings(os.environ.get("MIHOMO_TEST_CORE", "/bin/true"), str(core_config), "process"),
                          default_profile="work", profiles={"work": Profile(
                              name="work", http_listener="proxy", socks_listener="proxy",
                              credentials_file=str(credentials))}, bindings={"worker": Binding(
                                  name="worker", profile="work", adapter="systemd", target="worker.service")})
        scope.manager_path.write_text(render_manager(manager), encoding="utf-8")
        scope.manager_path.chmod(0o600)
        self.console = ConsoleService(self.app.config_path, app=self.app)

    def test_actual_status_retains_disabled_tun_and_required_facts(self):
        domain = self.app.status()
        document = self.console.runtime_document()
        self.assertEqual(document["overall"], domain["overall"])
        self.assertEqual(document["overall"], "FAIL", "stopped runtime must not look healthy")
        self.assertIs(document["core"]["running"], False)
        self.assertEqual(document["tun"]["state"], "disabled")
        self.assertEqual(document["config"]["path"], self.app.config_path)
        self.assertEqual(document["listeners"][0]["name"], "proxy")
        self.assertTrue(all(key in document for key in RUNTIME_FIELDS))
        self.assertNotIn("private-password", json.dumps(document))

    def test_actual_health_checks_are_not_dropped_and_use_domain_aggregation(self):
        from mihomoctl.envelope import combine_checks
        domain = self.app.health()
        document = self.console.health_document()
        self.assertEqual(len(document["checks"]), len(domain))
        self.assertEqual(document["overall"], combine_checks(domain))
        self.assertEqual(document["overall"], "FAIL")
        self.assertIn("runtime", [row["name"] for row in document["checks"]])

    def test_actual_profiles_resolve_default_bindings_and_mixed_listener_once(self):
        document = self.console.profiles_document()
        self.assertEqual(document["selected"], "work")
        self.assertEqual(document["profiles"][0]["listeners"], ["proxy"])
        self.assertEqual(document["bindings"]["worker"]["profile"], "work")
        self.assertNotIn("private-password", json.dumps(document))

    def test_named_listener_diagnosis_uses_explicit_private_expectations(self):
        before = dict(os.environ)
        expected = self.console.expected_proxy_environment()
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(expected, self.app.proxy_environment().variables())
        self.assertEqual(self.console.proxy_port(), self.app.resolve()[1][0].port)
        document = self.console.diagnose("process", str(os.getpid()))
        self.assertEqual(document["process"]["proxy_environment"]["expected"], 8)
        self.assertNotIn("private-password", json.dumps(document))
        self.assertEqual(dict(os.environ), before)

    @unittest.skipUnless(os.environ.get("MIHOMO_TEST_CORE"), "real Mihomo core required")
    def test_running_real_core_health_is_pass_and_stop_is_fail(self):
        from mihomoctl.errors import MihomoctlError
        try:
            self.console.lifecycle("start")
            document = self.console.health_document()
            self.assertEqual(document["overall"], "PASS", [
                (row["name"], row["status"]) for row in document["checks"]])
            self.assertEqual(self.console.runtime_document()["overall"], "PASS")
            self.assertIs(self.console.runtime_document()["core"]["running"], True)
            overview = self.console.read("overview")
            self.assertEqual(overview["controller"], "connected", overview.get("error"))
            self.assertIs(self.console.client().app, self.app)
            from mihomoctl.bridge import run_bridge
            environment = dict(os.environ)
            value, error = run_bridge(self.app.scope, ["nodes"], json_mode=True)
            self.assertIsNone(error)
            self.assertEqual(value["legacy_overall"], "PASS")
            self.assertEqual(dict(os.environ), environment)
        finally:
            try:
                self.app.lifecycle("stop")
            except MihomoctlError as error:
                self.fail("owned-core-stop-failed: " + error.code)
        self.assertEqual(self.console.health_document()["overall"], "FAIL")
        self.assertEqual(self.console.runtime_document()["overall"], "FAIL")


@requires_service
class RetiredWorkloadTests(unittest.TestCase):
    """Retired verbs map to generic answers and never reach a daemon."""

    def setUp(self):
        self.service = ConsoleService(Path("/nonexistent/mihomo-config.yaml"))

    def test_retired_commands_map_to_generic_health(self):
        for action in ("codex", "codex-diagnosis", "paseo", "paseo-preflight"):
            with self.subTest(action=action):
                document = self.service.shell(action)
                self.assertEqual(document["retired_command"], action)
                self.assertIn("checks", document)
                self.assertEqual(document["overall"], "UNVERIFIED")

    def test_unknown_actions_are_still_rejected(self):
        with self.assertRaises(ControlError):
            self.service.shell("reboot-everything")


class NoBashReentryTests(unittest.TestCase):
    """The interface layer must not shell out to the CLI for a decision."""

    FILES = ("controller_service.py", "controller_textual.py", "controller_console.py")

    def sources(self):
        for name in self.FILES:
            yield name, (ROOT / "mihomoctl" / "controller" / name).read_text(encoding="utf-8")

    def test_no_module_spawns_the_bash_cli(self):
        for name, text in self.sources():
            with self.subTest(module=name):
                self.assertNotIn("src/mihomoctl", text)
                self.assertNotIn('"bash", str(', text)

    def test_no_subprocess_call_uses_a_shell_or_a_shell_binary(self):
        """Any remaining subprocess must be a plain argv, never `bash -c`."""
        shells = ("bash", "sh", "zsh", "dash", "/bin/sh", "/bin/bash")
        for name, text in self.sources():
            with self.subTest(module=name):
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute) or node.func.attr not in ("run", "Popen"):
                        continue
                    owner = node.func.value
                    if not (isinstance(owner, ast.Name) and owner.id == "subprocess"):
                        continue
                    for keyword in node.keywords:
                        if keyword.arg == "shell":
                            self.fail("%s:%d must not use shell=True" % (name, node.lineno))
                    literal = node.args and isinstance(node.args[0], ast.Constant)
                    if literal and node.args[0].value in shells:
                        self.fail("%s:%d must not exec a shell interpreter" % (name, node.lineno))
                    if literal and node.args[0].value != "journalctl":
                        self.fail("%s:%d may only exec journalctl, found %r"
                                  % (name, node.lineno, node.args[0].value))

    def test_no_third_party_daemon_lifecycle_verb_survives_in_the_frontend(self):
        forbidden = ("install-unit", "ExecStop", "unit_owns_daemon", "wait_ready")
        for name, text in self.sources():
            with self.subTest(module=name):
                for token in forbidden:
                    self.assertNotIn(token, text, "%s still references %s" % (name, token))


class BridgeForwardTests(unittest.TestCase):
    """Synthesized controller options are appended, never spliced before values.

    The child parser takes command values as a ``nargs="*"`` positional and
    argparse cannot match an optional that precedes such a positional.  When
    ``run_bridge`` inserted ``--config`` at index 1, ``mihomoctl select GROUP
    NODE`` arrived as ``select --config PATH GROUP NODE`` and was rejected as
    ``invalid-options``; only a caller-written trailing ``--config`` worked.
    """

    CONFIG = "/srv/mihomoctl/mihomo/config.yaml"
    HOME = "/srv/mihomoctl/core-home"

    def parser(self):
        from mihomoctl.controller.controller_types import COMMANDS, Parser
        p = Parser()
        p.add_argument("command", choices=COMMANDS)
        p.add_argument("values", nargs="*")
        p.add_argument("--json", action="store_true")
        p.add_argument("--config")
        p.add_argument("--home-dir")
        return p

    def values(self, **overrides):
        base = {"config": self.CONFIG, "home": self.HOME}
        base.update(overrides)
        return base

    def test_every_bridged_command_parses_with_the_synthesized_config(self):
        cases = [
            ("select", ["Ai+", "\U0001F1FA\U0001F1F8 美国-BGP-05"]),
            ("latency", ["US-BGP-05"]),
            ("mode", ["rule"]),
            ("controller", ["status"]),
            ("subscription", ["apply", "a" * 32, "b" * 64]),
            ("nodes", []), ("groups", []), ("connections", []),
            ("traffic", []), ("ui", []), ("dashboard", []),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                forward = bridge_forward([command, *expected], self.values())
                parsed = self.parser().parse_args(forward)
                self.assertEqual(parsed.command, command)
                self.assertEqual(parsed.values, expected)
                self.assertEqual(parsed.config, self.CONFIG)

    def test_config_lands_after_the_values_not_before_them(self):
        forward = bridge_forward(["select", "Ai+", "NODE"], self.values())
        self.assertEqual(forward, ["select", "Ai+", "NODE", "--config", self.CONFIG])

    def test_home_dir_is_appended_only_for_the_commands_that_take_it(self):
        for command, takes_home in (("select", False), ("nodes", False),
                                    ("tui", True), ("health-check", True)):
            with self.subTest(command=command):
                forward = bridge_forward([command, "grp", "NODE"], self.values())
                self.assertEqual("--home-dir" in forward, takes_home)
                self.assertEqual(self.parser().parse_args(forward).home_dir,
                                 self.HOME if takes_home else None)

    def test_caller_supplied_options_are_never_duplicated(self):
        forward = bridge_forward(["select", "Ai+", "NODE", "--config", "/mine.yaml"],
                                 self.values())
        self.assertEqual(forward.count("--config"), 1)
        self.assertEqual(self.parser().parse_args(forward).config, "/mine.yaml")

    def test_json_is_appended_once_and_never_for_the_tui_passthrough(self):
        forward = bridge_forward(["nodes"], self.values(), json_mode=True)
        self.assertEqual(forward.count("--json"), 1)
        self.assertNotIn("--json", bridge_forward(["tui"], self.values(), json_mode=True))

    def test_a_legacy_fallback_without_a_managed_config_adds_no_config_option(self):
        forward = bridge_forward(["nodes"], {"config": None, "home": self.HOME})
        self.assertNotIn("--config", forward)


@requires_service
class PageModelTests(unittest.TestCase):
    """The console page model: subscriptions and ProxyProfile are distinct."""

    def load(self):
        path = ROOT / "mihomoctl" / "controller" / "controller_textual.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                continue
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
                continue
            except ValueError:
                pass
            # dict(zip(PAGES, (...))) is not a literal; rebuild it explicitly.
            call = node.value
            if isinstance(call, ast.Call) and call.args:
                inner = call.args[0]
                if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "zip":
                    first = inner.args[0]
                    keys = values[first.id] if isinstance(first, ast.Name) else ast.literal_eval(first)
                    names = ast.literal_eval(inner.args[1])
                    values[node.targets[0].id] = dict(zip(keys, names))
        return path.read_text(encoding="utf-8"), values

    def test_subscription_and_profile_are_separate_pages(self):
        text, values = self.load()
        pages = values["PAGES"]
        self.assertIn("subscriptions", pages)
        self.assertIn("profile", pages)
        self.assertNotIn("profiles", pages)
        self.assertEqual(values["PAGE_ALIASES"], {"profiles": "subscriptions"})

    def test_every_page_has_a_label_and_every_alias_target_exists(self):
        _, values = self.load()
        self.assertEqual(set(values["PAGE_NAMES"]), set(values["PAGES"]))
        for alias, target in values["PAGE_ALIASES"].items():
            self.assertIn(target, values["PAGES"], alias)
        for page in values["PRIMARY_PAGES"]:
            self.assertIn(page, values["PAGES"], page)

    def test_service_exposes_both_page_names(self):
        service = ConsoleService(Path("/nonexistent/mihomo-config.yaml"))
        self.assertEqual(service.read("subscriptions")["configuration"], "missing")
        self.assertEqual(service.read("profiles")["configuration"], "missing",
                         "the retained identifier must keep working")

    def test_profile_page_does_not_require_a_controller(self):
        service = ConsoleService(Path("/nonexistent/mihomo-config.yaml"))
        document = service.read("profile")
        self.assertEqual(document["overall"], "UNVERIFIED")
        self.assertNotIn("controller", document)

    def test_diagnostics_page_is_generic_health_without_workload_names(self):
        document = ConsoleService(Path("/nonexistent/mihomo-config.yaml")).read("diagnostics")
        self.assertNotIn("codex", json.dumps(document))
        self.assertNotIn("paseo", json.dumps(document))
        self.assertIn("checks", document)

    def test_unknown_page_is_rejected(self):
        with self.assertRaises(ControlError):
            ConsoleService(Path("/nonexistent/mihomo-config.yaml")).read("telemetry")


@requires_service
class RenderingTests(unittest.TestCase):
    """Presentation helpers must not invent a verdict."""

    def load_legacy(self):
        sys.path.insert(0, str(ROOT / "mihomoctl" / "controller"))
        try:
            from mihomoctl.controller import controller_console
            return controller_console
        finally:
            sys.path.pop(0)

    def test_describe_keeps_unknown_visible(self):
        legacy = self.load_legacy()
        self.assertEqual(legacy.describe(None), "unknown")
        self.assertEqual(legacy.describe({}), "unknown")
        self.assertEqual(legacy.describe([]), "")
        self.assertEqual(legacy.describe({"a": 1}), "a=1")
        self.assertEqual(legacy.describe(True), "yes")

    def test_describe_never_raises_on_nested_payloads(self):
        legacy = self.load_legacy()
        for value in ({"a": {"b": {"c": [1, 2]}}}, [None, {"x": None}], {"n": 1.5}):
            with self.subTest(value=value):
                self.assertIsInstance(legacy.describe(value), str)


class CompletionTests(unittest.TestCase):
    """Completion words must stay inside the frozen CLI contract."""

    def setUp(self):
        self.text = (ROOT / "completions" / "mihomoctl.bash").read_text(encoding="utf-8")

    def test_syntax_is_valid_bash(self):
        relative = Path("completions") / "mihomoctl.bash"
        result = subprocess.run(["bash", "-n", relative.as_posix()], cwd=str(ROOT),
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_v1_commands_are_offered(self):
        for word in ("init", "status", "health", "exec", "env", "profile", "integration",
                     "tun", "core", "service", "migrate"):
            self.assertIn(word, self.text, word)

    def test_frozen_subcommands_match_the_contract(self):
        """service/integration/core subcommand sets are part of the contract."""
        self.assertIn("'install start stop restart status uninstall'", self.text)
        self.assertIn("'list show check export install remove'", self.text)
        self.assertIn("'install update adopt list'", self.text)
        self.assertIn("'show export'", self.text)

    def test_retired_or_invented_surface_is_absent(self):
        """Words that were corrected must not creep back into completion."""
        for word in ("allow-unpinned", "--shell bash zsh fish", "install remove status",
                     "'preview apply --json"):
            self.assertNotIn(word, self.text, word)
        # migrate is flag-driven, not subcommand-driven.
        self.assertIn("'--dry-run --apply --remove-loader", self.text)

    def test_env_export_offers_binding_output_and_reveal(self):
        self.assertIn("--profile --binding --output --reveal", self.text)

    def test_scope_flags_are_global_user_and_system(self):
        self.assertIn("--user", self.text)
        self.assertIn("--system", self.text)
        self.assertNotIn("--scope", self.text,
                         "architecture-v1.md fixes global --user/--system; --scope is not a V1 flag")

    def test_retired_daemon_subcommands_are_not_offered(self):
        for word in ("install-unit", "'paseo exec", "paseo start"):
            self.assertNotIn(word, self.text, word)

    def complete(self, *words):
        script = 'source "$1"; shift; COMP_WORDS=("$@"); COMP_CWORD=$((${#COMP_WORDS[@]}-1)); _mihomoctl_complete; printf "%s\\n" "${COMPREPLY[@]}"'
        result = subprocess.run(["bash", "-c", script, "completion-test",
                                 str(ROOT / "completions/mihomoctl.bash"), "mihomoctl", *words],
                                capture_output=True, text=True, check=True)
        return set(result.stdout.split())

    def test_completion_understands_global_scope_and_child_argument_boundary(self):
        self.assertIn("start", self.complete("--system", "sta"))
        self.assertIn("install", self.complete("--system", "service", "in"))
        self.assertIn("--binding", self.complete("--user", "exec", "--b"))
        self.assertEqual(self.complete("exec", "--", "tool", "--b"), set())


@requires_service
class CommandHelpTests(unittest.TestCase):
    """Published flags must be discoverable before a user initializes config."""

    def test_public_command_help_matches_the_published_contract(self):
        cases = (
            (("--help",), ("start", "stop", "restart", "status", "logs", "config")),
            (("profile", "--help"), ("validate", "set-default")),
            (("service", "--help"), ("install", "uninstall", "status")),
            (("integration", "--help"), ("show", "check", "export", "install", "remove")),
            (("env", "export", "--help"), ("--profile", "--binding", "--output", "--reveal")),
            (("health", "check", "--help"), ("--profile", "--binding", "--egress-url")),
            (("exec", "--help"), ("--profile", "--binding")),
            (("config", "validate", "--help"), ("--file",)),
            (("core", "install", "--help"), ("--version", "--sha256")),
            (("migrate", "--help"), ("--dry-run", "--apply")),
        )
        with tempfile.TemporaryDirectory(prefix="mihomoctl-help-") as folder:
            environment = dict(os.environ, HOME=folder, XDG_CONFIG_HOME=folder + "/config")
            for args, flags in cases:
                with self.subTest(command=args):
                    result = subprocess.run([sys.executable, "-m", "mihomoctl", *args],
                                            cwd=ROOT, env=environment, capture_output=True,
                                            text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, "help failed for " + " ".join(args))
                    for flag in flags:
                        self.assertIn(flag, result.stdout)


class DocumentationTests(unittest.TestCase):
    """User documentation must describe V1, not the retired shell hook."""

    FILES = ("README.md", "README.en.md", "README.zh-CN.md", "INSTALL.md", "SECURITY.md",
             "CHANGELOG.md", "docs/README.md", "docs/en/README.md", "docs/zh-CN/README.md")

    def documents(self):
        for name in self.FILES:
            path = ROOT / name
            if path.exists():
                yield name, path.read_text(encoding="utf-8")

    def test_entry_documents_exist(self):
        for name in ("README.md", "README.en.md", "README.zh-CN.md", "INSTALL.md", "SECURITY.md"):
            self.assertTrue((ROOT / name).exists(), name)

    def test_no_document_teaches_the_retired_startup_hook(self):
        """A document may name the retired hook only when it also marks it retired."""
        banned = ("CODEX_REMOTE_PAYLOAD", "proxy_on || exit 1", "bashrc-loader")
        for name, text in self.documents():
            with self.subTest(document=name):
                retired = "1.0.0" in text and ("\u9000\u5f79" in text or "retired" in text.lower()
                                                or "removed" in text.lower())
                for token in banned:
                    if token in text:
                        self.assertTrue(retired,
                                        "%s mentions %s without marking it retired" % (name, token))

    def test_entry_documents_refuse_the_startup_file_option(self):
        """No entry document may still tell a new setup to use --bashrc."""
        for name in ("README.md", "README.en.md", "INSTALL.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(document=name):
                self.assertIn(".bashrc", text)
                self.assertNotIn("install.sh --port \"$PROXY_PORT\" --bashrc", text)

    def test_entry_documents_state_the_no_startup_file_boundary(self):
        """The first-run boundary must be stated, in either language."""
        for name in ("README.md", "README.en.md", "INSTALL.md", "SECURITY.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(document=name):
                self.assertTrue(
                    "shell startup file" in text.lower() or "\u542f\u52a8\u6587\u4ef6" in text,
                    "%s does not state that no startup file is written" % name)

    def test_no_document_contains_private_host_or_user_values(self):
        # Composed from segments: this file is scanned too and must not contain a
        # private identifier in plaintext.
        user = "liu" + "zq"
        patterns = ("/home/" + user, "/home/" + user + "pc", user + "@", "@" + user,
                    "\\Users\\" + user, user + "@" + "localhost")
        for name, text in self.documents():
            with self.subTest(document=name):
                for pattern in patterns:
                    self.assertNotIn(pattern, text, "%s leaks %s" % (name, pattern))

    def test_changelog_records_v1_without_claiming_acceptance(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("1.0.0", text)
        self.assertNotIn("已发布 1.0.0", text)
        self.assertNotIn("verified on multiple", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
