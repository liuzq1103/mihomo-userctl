"""Self-update regressions: disposable HOME, fake service, no public network.

Most integration cases bypass the separately tested release validation profile;
the installer, atomic publication, provenance, rollback and CLI are real.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

if sys.platform != "linux":
    raise unittest.SkipTest("Linux installer and flock integration")

from scripts import install_support as ins
from scripts import update as up
from scripts import migrate

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "release-manifest.json").read_text())["version"]
NEXT = BASE.rsplit(".", 1)[0] + "." + str(int(BASE.rsplit(".", 1)[1]) + 1)
TAG = "v" + NEXT
COMMIT = "a" * 40
SECRET = "private-fixture-" + "0123456789abcdef"


def put(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def copy_source(destination):
    shutil.copytree(ROOT, destination, ignore=shutil.ignore_patterns(
        ".git", ".tmp-*", "__pycache__", "*.pyc", "future-roadmap-and-agent-prompts.md"))
    for path in destination.rglob("*"):
        path.chmod(0o755 if path.is_dir() or path.name in ("install.sh", "uninstall.sh", "mihomoctl") else 0o644)


def target_source(destination):
    copy_source(destination)
    for name in ("install.sh", "src/common.bash", "release-manifest.json"):
        path = destination / name
        path.write_text(path.read_text().replace(BASE, NEXT))


class FakeRelease:
    def __init__(self, source):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in source.rglob("*"):
                if path.is_file():
                    archive.write(path, "release/" + path.relative_to(source).as_posix())
        self.body = stream.getvalue()
        self.downloads = 0

    def resolve(self, tag=None):
        return {"kind": "github-release-source", "repository": up.REPO, "tag": tag or TAG,
                "commit": COMMIT, "release_id": 123,
                "archive_url": "https://codeload.github.com/" + up.REPO + "/zip/" + COMMIT,
                "official_digest": None,
                "verification": "HTTPS-GitHub-tag-to-commit;no-independent-archive-digest-or-signature"}

    def archive(self, source, destination):
        self.downloads += 1
        ins.atomic_bytes(destination, self.body)
        source["archive_sha256"] = hashlib.sha256(self.body).hexdigest()


class SourceTests(unittest.TestCase):
    def test_v020_runtime_receipt_is_accepted_only_with_its_exact_known_set(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            generation = root / "generations" / ("a" * 32)
            generation.mkdir(parents=True)
            hashes = {}
            for name in ins.RUNTIME_020:
                put(generation / name, "v0.2.0 fixture " + name, 0o644)
                hashes[name] = ins.digest(generation / name)
            record = {"install_root": str(root), "generation": generation.name,
                      "version": "0.2.0", "runtime_hashes": hashes,
                      "bootstrap_hashes": {name: "fixture" for name in
                                           ("mihomoctl", "common.bash", "shell.bash", "completion.bash")}}
            ins.verify_generation(record)
            record["runtime_hashes"] = dict(hashes)
            record["runtime_hashes"].pop("acceptance.py")
            with self.assertRaises(ins.InstallError):
                ins.verify_generation(record)

    def test_v021_runtime_receipt_remains_valid_for_deterministic_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            generation = root / "generations" / ("b" * 32)
            generation.mkdir(parents=True)
            hashes = {}
            for name in ins.RUNTIME_021:
                put(generation / name, "v0.2.1 fixture " + name, 0o644)
                hashes[name] = ins.digest(generation / name)
            record = {"install_root": str(root), "generation": generation.name,
                      "version": "0.2.1", "runtime_hashes": hashes,
                      "bootstrap_hashes": {name: "fixture" for name in
                                           ("mihomoctl", "common.bash", "shell.bash", "completion.bash")}}
            ins.verify_generation(record)
            record["runtime_hashes"] = dict(hashes, **{"reporting.py": "unexpected"})
            with self.assertRaises(ins.InstallError):
                ins.verify_generation(record)

    def test_release_resolves_annotated_tag_and_records_exact_commit(self):
        client = up.GitHub()
        release = dict(tag_name=TAG, draft=False, prerelease=False, published_at="date", id=123)
        with patch.object(client, "api", side_effect=[release,
                {"object": {"type": "tag", "sha": "b" * 40}},
                {"object": {"type": "commit", "sha": COMMIT}}]) as api:
            result = client.resolve(TAG)
        self.assertEqual(result["commit"], COMMIT)
        self.assertEqual(api.call_count, 3)
        self.assertIn(COMMIT, result["archive_url"])
        self.assertIsNone(result["official_digest"])

    def test_drafts_prereleases_invalid_tags_and_tag_cycles_rejected(self):
        for tag in ("main", "v1.2.3-rc1", "../../private", "v01.2.3"):
            with self.subTest(tag=tag), self.assertRaises(up.UpdateError):
                up.version(tag)
        for key in ("draft", "prerelease"):
            release = dict(tag_name=TAG, draft=False, prerelease=False, published_at="date", id=123)
            release[key] = True
            with patch.object(up.GitHub, "api", return_value=release), self.assertRaises(up.UpdateError):
                up.GitHub().resolve(TAG)

    def test_download_error_hides_private_upstream_values(self):
        client = up.GitHub()
        with patch.object(client.opener, "open", side_effect=OSError(SECRET)):
            with self.assertRaises(up.UpdateError) as result:
                client.get(up.API, 1024)
        self.assertNotIn(SECRET, str(result.exception))

    def test_nonofficial_redirect_rejected(self):
        with self.assertRaises(up.UpdateError):
            up.OfficialRedirect().redirect_request(None, None, 302, "", {}, "https://example.org/private")

    def test_archive_rejects_traversal_symlinks_collisions_and_multiple_roots(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            cases = [["../escape"], ["/escape"], ["root/../escape"], ["root\\escape"],
                     ["root/a", "root/A"], ["one/a", "two/b"], ["root/drive:c"], ["root/link"]]
            for index, names in enumerate(cases):
                with self.subTest(names=names):
                    archive = work / "bad.zip"
                    with zipfile.ZipFile(archive, "w") as package:
                        for name in names:
                            entry = zipfile.ZipInfo(name)
                            if name == "root/link":
                                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                            package.writestr(entry, "target")
                    with self.assertRaises(up.UpdateError):
                        up.extract(archive, work / str(index))
            archive.write_bytes(b"truncated archive")
            with self.assertRaises(up.UpdateError):
                up.extract(archive, work / "truncated")

    def test_archive_bounds_and_missing_or_incompatible_manifest(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            archive = work / "big.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("root/test", "0123456789")
            with patch.object(up, "MAX_EXPANDED", 5), self.assertRaises(up.UpdateError):
                up.extract(archive, work / "expanded")
            with self.assertRaises(up.UpdateError):
                up.validate(work, TAG)
            put(work / "release-manifest.json", json.dumps(dict(format=1, version=NEXT,
                update_protocol=99, validation_profile="installation-v1")))
            with self.assertRaises(up.UpdateError):
                up.validate(work, TAG)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix="muc-source-fixture-")
        cls.source = Path(cls.shared.name) / "current"
        copy_source(cls.source)
        cls.target = Path(cls.shared.name) / "target"
        target_source(cls.target)
        cls.release = FakeRelease(cls.target)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="muc-update-fixture-")
        self.addCleanup(self.work.cleanup)
        self.base = Path(self.work.name)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        self.config = self.home / "custom config"
        self.data = self.home / "custom data"
        self.startup = self.home / "shell startup.bash"
        self.root = self.data / "mihomo-userctl"
        self.bin = self.home / ".local/bin/mihomoctl"
        self.commands = self.base / "bin"
        self.commands.mkdir()
        self.state = self.base / "state"
        self.enable = self.base / "enabled"
        put(self.state, "inactive")
        put(self.enable, "enabled")
        put(self.startup, "# my private shell customization\nexport MY_VALUE=unchanged\n", 0o644)
        put(self.config / "mihomo/mihomo-shell.conf", "MIHOMO_SERVICE=mihomo-custom@fixture\n"
            "MIHOMO_PORT=28443\nMIHOMO_READY_URL=https://example.com/\n"
            "MIHOMO_READY_TIMEOUT=2\nMIHOMO_STOP_TIMEOUT=1\n")
        put(self.config / "mihomo/client.env", "\n".join(
            name + "='" + scheme + "://user:" + SECRET + "@127.0.0.1:28443'"
            for name, scheme in (("MIHOMO_HTTP_PROXY", "http"), ("MIHOMO_HTTPS_PROXY", "http"),
                                 ("MIHOMO_ALL_PROXY", "socks5h"))) + "\n")
        put(self.config / "mihomo/config.yaml", "# fixture core config " + SECRET)
        put(self.config / "mihomo/providers/private.yaml", "# untouched provider " + SECRET)
        put(self.home / ".local/bin/mihomo", "#!/bin/sh\necho core-fixture\n", 0o755)
        put(self.commands / "systemctl", '''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIXTURE_ROOT/calls"
case "$*" in
 '--user show-environment') exit 0;;
 '--user is-active --quiet mihomo-custom@fixture') [[ $(<"$FIXTURE_ROOT/state") == active ]];;
 '--user is-active mihomo-custom@fixture') cat "$FIXTURE_ROOT/state"; [[ $(<"$FIXTURE_ROOT/state") == active ]] || exit 3;;
 '--user is-enabled mihomo-custom@fixture') cat "$FIXTURE_ROOT/enabled"; [[ $(<"$FIXTURE_ROOT/enabled") == enabled ]] || exit 1;;
 *) echo forbidden-service-operation >&2; exit 99;;
esac
''', 0o755)
        put(self.commands / "ss", "#!/bin/sh\nprintf 'LISTEN 0 4096 127.0.0.1:28443 0.0.0.0:*\\n'\n", 0o755)
        for name in ("curl", "journalctl"):
            put(self.commands / name, "#!/bin/sh\nexit 0\n", 0o755)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MIHOMO_") and
                 k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
        clean.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.config), XDG_DATA_HOME=str(self.data),
                     PATH=str(self.commands) + ":/usr/bin:/bin", FIXTURE_ROOT=str(self.base), PYTHONDONTWRITEBYTECODE="1")
        self.environ = patch.dict(os.environ, clean, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.install(self.source)

    def install(self, source):
        proc = subprocess.run(["bash", str(source / "install.sh"), "--bashrc", str(self.startup),
                               "--preserve-service-state"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def snapshot(self):
        # All active files, core/provider/config content and modes; exclude private
        # staged generations/backups/lock files which dry-run may create.
        record = ins.metadata(self.root)
        paths = [self.bin, self.startup, self.home / ".local/bin/mihomo"]
        paths += list((self.config / "mihomo").rglob("*"))
        paths += [self.root / name for name in ("common.bash", "shell.bash", "completion.bash")]
        paths += list((self.root / "generations" / record["generation"]).rglob("*"))
        return (os.readlink(self.root / "current"),
                {str(p): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in paths if p.is_file()},
                self.state.read_text(), self.enable.read_text())

    def run_update(self, *args, validate=False, client=None):
        output = io.StringIO()
        validator = contextlib.nullcontext() if validate else patch.object(up, "validate")
        with validator, contextlib.redirect_stdout(output):
            rc = up.cli(["--install-root", str(self.root), "--current-version", BASE] + list(args),
                        client or self.release)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn("http://user:", output.getvalue())
        return rc, output.getvalue()

    def backup(self):
        return max((self.data / "mihomo-userctl-backups").iterdir(), key=lambda p: p.stat().st_mtime_ns)

    def assert_no_service_mutations(self):
        calls = (self.base / "calls").read_text().splitlines()
        self.assertTrue(all(line.startswith(("--user show-environment", "--user is-active", "--user is-enabled"))
                            for line in calls), calls)

    def test_check_and_dry_run_do_not_change_active_install(self):
        before = self.snapshot()
        self.assertEqual(self.run_update("--check")[0], 0)
        rc, output = self.run_update("--version", TAG, "--dry-run")
        self.assertEqual(rc, 0, output)
        self.assertIn("available=yes", self.run_update("--check")[1])
        self.assertIn("UNVERIFIED\tplanned-final-checks", output)
        self.assertEqual(self.snapshot(), before)
        self.assert_no_service_mutations()

    def test_zip_install_source_removed_custom_paths_preservation_and_repeated_update(self):
        snapshot_source = self.base / "zip-source"
        copy_source(snapshot_source)
        self.install(snapshot_source)
        shutil.rmtree(snapshot_source)
        self.assertEqual(ins.metadata(self.root)["source"]["kind"], "source-snapshot")
        before = up.preserved(ins.metadata(self.root))
        core = (self.home / ".local/bin/mihomo").read_bytes()
        provider = (self.config / "mihomo/providers/private.yaml").read_bytes()
        # Clear XDG just as a later fresh login might do. CLI and updater use saved paths.
        os.environ.pop("XDG_CONFIG_HOME")
        os.environ.pop("XDG_DATA_HOME")
        proc = subprocess.run([str(self.bin), "doctor", "--offline"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 3, output)
        after = ins.metadata(self.root)
        self.assertEqual(after["version"], NEXT)
        self.assertEqual(after["source"]["commit"], COMMIT)
        self.assertEqual(len(after["source"]["archive_sha256"]), 64)
        self.assertEqual(up.preserved(after), before)
        self.assertEqual((self.home / ".local/bin/mihomo").read_bytes(), core)
        self.assertEqual((self.config / "mihomo/providers/private.yaml").read_bytes(), provider)
        self.assertIn("UNVERIFIED\tlistener-and-auth", output)
        self.assertIn("DEFERRED\tnew-shell", output)
        self.assertIn("DEFERRED\tlong-lived-clients", output)
        self.assertNotIn("PASS\toverall", output)
        self.assert_no_service_mutations()
        snapshot = self.snapshot()
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        self.assertEqual(self.snapshot(), snapshot)
        # Target extraction is gone; installed CLI must still work.
        proc = subprocess.run([str(self.bin), "version"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(NEXT, proc.stdout)
        environment = dict(os.environ)
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        proc = subprocess.run([str(self.bin), "update", "--version", "main"],
                              env=environment, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("use-a-published-stable", proc.stdout)
        self.assertFalse(list(self.root.rglob("__pycache__")))
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-c",
                               'source "$1"; declare -F with_proxy; printf "%s" "$MIHOMO_USERCTL_VERSION"',
                               "_", str(self.startup)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("with_proxy", proc.stdout)
        self.assertIn(NEXT, proc.stdout)

    def test_v021_receipt_updates_deterministically_to_v022(self):
        record = ins.metadata(self.root)
        generation = self.root / "generations" / record["generation"]
        record["version"] = "0.2.1"
        record["runtime_hashes"].pop("reporting.py")
        (generation / "reporting.py").unlink()
        ins.write_json(generation / "installation.json", record)
        ins.verify_installed(record)

        rc, output = self.run_update("--version", "v0.2.2",
                                     client=FakeRelease(self.source))
        self.assertEqual(rc, 3, output)
        updated = ins.metadata(self.root)
        self.assertEqual(updated["version"], "0.2.2")
        self.assertIn("reporting.py", updated["runtime_hashes"])
        self.assertTrue((self.root / "generations" / updated["generation"] /
                         "reporting.py").is_file())
        proc = subprocess.run([str(self.bin), "version"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("0.2.2", proc.stdout)

    def test_git_checkout_commit_is_recorded_and_deleted_checkout_not_needed(self):
        source = self.base / "git-source"
        copy_source(source)
        for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c",
                "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", str(source)] + args, check=True, capture_output=True)
        expected = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        self.install(source)
        self.assertEqual(ins.metadata(self.root)["source"]["commit"], expected)
        shutil.rmtree(source)
        self.assertEqual(self.run_update("--version", TAG)[0], 3)

    def test_download_validation_and_incompatible_failures_leave_install_unchanged(self):
        before = self.snapshot()
        with patch.object(self.release, "archive", side_effect=OSError(SECRET)):
            self.assertEqual(self.run_update("--version", TAG)[0], 1)
        with patch.object(up, "validate", side_effect=up.UpdateError("fixture-validation-failed")):
            self.assertEqual(self.run_update("--version", TAG, validate=True)[0], 1)
        with patch.object(up, "validate", side_effect=up.UpdateError("incompatible-protocol", 2)):
            self.assertEqual(self.run_update("--version", TAG, validate=True)[0], 2)
        self.assertEqual(self.snapshot(), before)
        self.assert_no_service_mutations()

    def test_direct_install_rejects_inconsistent_source_version_before_replacement(self):
        before = self.snapshot()
        source = self.base / "inconsistent-source"
        copy_source(source)
        manifest = source / "release-manifest.json"
        manifest.write_text(manifest.read_text().replace(BASE, NEXT))
        proc = subprocess.run(["bash", str(source / "install.sh"), "--bashrc", str(self.startup),
                               "--preserve-service-state"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("source-version-markers-disagree", proc.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assert_no_service_mutations()

    def test_install_and_publication_failure_roll_back(self):
        before = self.snapshot()
        for marker, injection in (("atomic_install \"$generation/bootstrap/shell.bash\"", "exit 17\n"),
                                  ('python3 "$support" publish', 'printf damaged >> "$generation/common.bash"\n')):
            with self.subTest(marker=marker):
                source = self.base / ("broken-" + str(len(list(self.base.glob("broken-*")))))
                target_source(source)
                path = source / "install.sh"
                text = path.read_text()
                index = text.index(marker)
                path.write_text(text[:index] + injection + text[index:])
                rc, output = self.run_update("--version", TAG, client=FakeRelease(source))
                self.assertEqual(rc, 1, output)
                self.assertIn("PASS\trollback\trestored", output)
                self.assertEqual(self.snapshot(), before)

    def test_final_check_exception_rolls_back_complete_update(self):
        before = self.snapshot()
        real_state = up.service_state
        calls = []

        def state(service):
            calls.append(service)
            if len(calls) == 2:
                raise up.UpdateError("fixture-final-check-failed")
            return real_state(service)

        with patch.object(up, "service_state", side_effect=state):
            rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 1, output)
        self.assertIn("PASS\trollback", output)
        self.assertEqual(self.snapshot(), before)

    def test_manual_rollback_is_private_source_independent_and_repeatable(self):
        before = self.snapshot()
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        backup = self.backup()
        for _ in range(2):
            proc = subprocess.run([sys.executable, str(backup / "restore.py"), "rollback", str(backup)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_rollback_refuses_to_overwrite_new_personal_edits(self):
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        self.startup.write_text(self.startup.read_text() + "# later user edit\n")
        with self.assertRaises(ins.InstallError):
            ins.rollback(self.backup())
        self.assertIn("later user edit", self.startup.read_text())

    def test_damaged_backup_is_rejected_before_active_pointer_or_files_change(self):
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        before = self.snapshot()
        backup = self.backup()
        put(backup / "bashrc", "damaged fixture")
        with self.assertRaises(ins.InstallError) as result:
            ins.rollback(backup)
        self.assertIn("backup-payload-damaged", str(result.exception))
        self.assertEqual(self.snapshot(), before)

    def test_interrupted_rollback_can_be_retried(self):
        original = self.snapshot()
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        backup = self.backup()
        real_atomic = ins.atomic_bytes
        writes = []

        def fail_second(path, data, mode=600):
            writes.append(path)
            if len(writes) == 2:
                raise OSError("fixture disk failure")
            return real_atomic(path, data, mode)

        with patch.object(ins, "atomic_bytes", side_effect=fail_second), self.assertRaises(OSError):
            ins.rollback(backup)
        with contextlib.redirect_stdout(io.StringIO()):
            ins.rollback(backup)
        self.assertEqual(self.snapshot(), original)

    def test_concurrent_update_and_pending_transaction_fail_closed(self):
        before = self.snapshot()
        with ins.locked(self.data):
            self.assertEqual(self.run_update("--version", TAG)[0], 4)
        ins.write_json(self.root / "pending-install.json", {"backup": str(self.backup())})
        self.assertEqual(self.run_update("--version", TAG)[0], 2)
        (self.root / "pending-install.json").unlink()
        self.assertEqual(self.snapshot(), before)

    def test_missing_metadata_and_local_customization_and_downgrade_refused(self):
        record = ins.metadata(self.root)
        meta = self.root / "generations" / record["generation"] / "installation.json"
        original = meta.read_bytes()
        meta.unlink()
        rc, output = self.run_update("--check")
        self.assertEqual(rc, 0)
        self.assertIn("unknown;one-time-migration-required", output)
        self.assertEqual(self.run_update("--version", TAG)[0], 2)
        ins.atomic_bytes(meta, original)
        self.assertEqual(self.run_update("--version", "v0.0.1")[0], 2)
        code = meta.parent / "common.bash"
        code.write_text(code.read_text() + "# local modification\n")
        rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 2)
        self.assertIn("installed-code-modified", output)

    def test_active_service_verifier_failure_and_timeout_do_not_hide_installed_files(self):
        put(self.state, "active")
        real_run = subprocess.run

        def run(command, **kwargs):
            if len(command) > 1 and str(command[1]).endswith("/acceptance.py"):
                self.assertIn("enabled", command)
                return subprocess.CompletedProcess(command, 1, "FAIL\thttp-auth\tcurl_rc=7;http=000\n", SECRET)
            return real_run(command, **kwargs)

        with patch.object(up.subprocess, "run", side_effect=run):
            rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 5, output)
        self.assertIn("PASS\tfiles-installed", output)
        self.assertIn("FAIL\toverall-acceptance", output)
        self.assertEqual(self.state.read_text(), "active")
        self.assert_no_service_mutations()

    def test_active_acceptance_timeout_keeps_installed_result_pending(self):
        put(self.state, "active")
        real_run = subprocess.run

        def run(command, **kwargs):
            if len(command) > 1 and str(command[1]).endswith("/acceptance.py"):
                raise subprocess.TimeoutExpired(command, 100, output=SECRET)
            return real_run(command, **kwargs)

        with patch.object(up.subprocess, "run", side_effect=run):
            rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 3, output)
        self.assertIn("PASS\tfiles-installed", output)
        self.assertIn("UNVERIFIED\tlistener-and-auth", output)
        self.assertNotIn("PASS\toverall", output)

    def test_killed_installer_leaves_recoverable_transaction_and_complete_old_generation(self):
        before = self.snapshot()
        source = self.base / "interrupted-source"
        target_source(source)
        path = source / "install.sh"
        text = path.read_text().replace('python3 "$support" publish',
                                       'kill -KILL "$$"\npython3 "$support" publish', 1)
        path.write_text(text)
        rc, output = self.run_update("--version", TAG, client=FakeRelease(source))
        self.assertEqual(rc, 1, output)
        self.assertTrue((self.root / "pending-install.json").exists())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_update("--version", TAG)[0], 2)
        backup = self.backup()
        proc = subprocess.run([sys.executable, str(backup / "restore.py"), "rollback", str(backup)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse((self.root / "pending-install.json").exists())
        self.assertEqual(self.snapshot(), before)

    def test_legacy_flat_install_migrates_with_explicit_paths_and_unknown_history(self):
        record = ins.metadata(self.root)
        generation = self.root / "generations" / record["generation"]
        for name in ("common.bash", "shell.bash", "completion.bash"):
            shutil.copyfile(generation / name, self.root / name)
        shutil.copyfile(generation / "mihomoctl", self.bin)
        (self.root / "current").unlink()
        original = up.preserved(dict(record, generation=None))
        arguments = ["--version", TAG, "--config-home", str(self.config),
                     "--data-home", str(self.data), "--bashrc", str(self.startup)]
        output = io.StringIO()
        with patch.object(up, "validate"), contextlib.redirect_stdout(output):
            self.assertEqual(migrate.cli(arguments + ["--dry-run"], self.release), 0)
            self.assertFalse((self.root / "current").exists())
            self.assertEqual(migrate.cli(arguments, self.release), 3)
        self.assertIn("UNVERIFIED\thistorical-source\tunknown", output.getvalue())
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(ins.metadata(self.root)["source"]["commit"], COMMIT)
        self.assertEqual(up.preserved(ins.metadata(self.root)), original)
        self.assert_no_service_mutations()

    def test_retag_and_stale_backup_are_rejected(self):
        self.assertEqual(self.run_update("--version", TAG)[0], 3)
        backup = self.backup()
        resolved = self.release.resolve(TAG)
        resolved["commit"] = "b" * 40
        with patch.object(self.release, "resolve", return_value=resolved):
            rc, output = self.run_update("--version", TAG)
        self.assertEqual(rc, 2)
        self.assertIn("published-tag-moved", output)
        # A different complete install creates a later generation.
        self.install(self.target)
        with self.assertRaises(ins.InstallError):
            ins.rollback(backup)

    def test_unknown_service_state_prevents_install_and_private_symlink_path_is_rejected(self):
        before = self.snapshot()
        put(self.state, "activating")
        self.assertEqual(self.run_update("--version", TAG)[0], 2)
        put(self.state, "inactive")
        self.assertEqual(self.snapshot(), before)
        link = self.home / "unsafe-link"
        link.symlink_to(self.config, target_is_directory=True)
        with self.assertRaises(ins.InstallError):
            ins.safe_path(link / "mihomo/client.env")

    def test_symlink_backup_parent_is_refused_before_any_install_writes(self):
        before = self.snapshot()
        parent = self.data / "mihomo-userctl-backups"
        saved = self.data / "original-backups"
        parent.rename(saved)
        outside = self.home / "unrelated-directory"
        outside.mkdir(mode=0o755)
        put(outside / "sentinel", "keep this")
        parent.symlink_to(outside, target_is_directory=True)
        proc = subprocess.run(["bash", str(self.source / "install.sh"), "--bashrc", str(self.startup)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unsafe installation paths", proc.stderr)
        self.assertEqual((outside / "sentinel").read_text(), "keep this")
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
        self.assertEqual(self.snapshot(), before)

    def test_target_real_validation_profile_runs_without_git(self):
        # This exercises the actual isolated release profile once, not a mock.
        rc, output = self.run_update("--version", TAG, "--dry-run", validate=True)
        self.assertEqual(rc, 0, output)
        self.assertIn("PASS\ttarget-validation", output)


if __name__ == "__main__":
    unittest.main()
