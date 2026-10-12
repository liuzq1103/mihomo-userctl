#!/usr/bin/env python3
"""Run V1 checks from a private Linux copy; never weaken production path checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".aws", ".codex", ".agents", "__pycache__", ".pytest_cache", "dist", "build", ".venv"}


def snapshot(destination, public=False):
    def ignore(_directory, names):
        return [n for n in names if n in EXCLUDED or n.startswith(("MainServer_", ".tmp"))
                or n.endswith((".egg-info", ".pyc", ".baiduyun.uploading.cfg"))]
    shutil.copytree(ROOT, destination, ignore=ignore, symlinks=True)
    for path in [destination, *destination.rglob("*")]:
        if path.is_symlink():
            raise RuntimeError("source-snapshot-symlink-refused")
        executable = path.suffix in (".sh", ".bash") or path.name == "mihomoctl"
        path.chmod((0o755 if public else 0o700) if path.is_dir() or executable
                   else (0o644 if public else 0o600))


def run(args, cwd, env=None):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)


def source_evidence():
    """Bind CI observations to their source commit and actual Ubuntu version."""
    command = ["git", "-c", "safe.directory=" + str(ROOT), "-C", str(ROOT)]
    try:
        commit = subprocess.check_output([*command, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        dirty = subprocess.run([*command, "diff", "--quiet", "HEAD", "--"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, True
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    return {"commit": commit, "source_dirty": dirty, "os": release.get("ID"),
            "ubuntu": release.get("VERSION_ID"), "python": platform.python_version()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--unit", action="store_true")
    group.add_argument("--real-core", action="store_true")
    group.add_argument("--privileged", action="store_true")
    parser.add_argument("--core", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--pattern", action="append", help="focused unit-test filename pattern")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux required; use WSL or the Ubuntu CI VM")
    if args.pattern and not args.unit:
        parser.error("--pattern is only available for unit checks; acceptance suites are fixed")
    if args.privileged:
        if os.geteuid() != 0 or os.environ.get("MIHOMO_V1_DISPOSABLE_VM") != "1":
            parser.error("privileged acceptance requires an explicitly disposable root VM")
        if not args.core or not args.wheelhouse:
            parser.error("--core and --wheelhouse required")
    if args.real_core and not args.core:
        parser.error("--core required; mandatory real-core checks cannot skip")
    with tempfile.TemporaryDirectory(prefix="mihomoctl-v1-ci-") as folder:
        base = Path(folder)
        if args.privileged:
            base.chmod(0o755)
        source = base / "source"
        snapshot(source, public=args.privileged)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        evidence = source_evidence()
        if args.core:
            core = args.core.resolve(strict=True)
            if args.privileged:
                trusted_core = base / "mihomo"
                shutil.copyfile(core, trusted_core)
                trusted_core.chmod(0o755)
                core = trusted_core
            env["MIHOMO_TEST_CORE"] = str(core)
            evidence["core_sha256"] = hashlib.sha256(core.read_bytes()).hexdigest()
        env["MIHOMO_V1_SOURCE_EVIDENCE"] = json.dumps(evidence, sort_keys=True)
        if args.privileged:
            venv = base / "venv"
            run([sys.executable, "-m", "venv", venv], source)
            python = venv / "bin/python"
            wheelhouse = base / "wheelhouse"
            wheelhouse.mkdir(mode=0o700)
            for candidate in args.wheelhouse.resolve().glob("*.whl"):
                if candidate.is_symlink() or not candidate.is_file():
                    parser.error("unsafe-wheelhouse-entry")
                shutil.copyfile(candidate, wheelhouse / candidate.name)
                (wheelhouse / candidate.name).chmod(0o600)
            wheels = sorted(wheelhouse.glob("mihomoctl-*.whl"))
            if len(wheels) != 1:
                parser.error("wheelhouse must contain exactly one release wheel")
            run([python, "-m", "pip", "install", "--no-index", "--find-links",
                 wheelhouse, wheels[0]], source)
            env.update(MIHOMO_V1_PRIVILEGED="1", MIHOMO_V1_PYTHON=str(python),
                       MIHOMO_V1_SOURCE=str(source), MIHOMO_V1_FIXTURE=str(base),
                       MIHOMO_V1_WHEELHOUSE=str(wheelhouse))
            if args.report:
                env["MIHOMO_V1_REPORT"] = str(args.report.resolve())
            run([python, source / "tests/test_v1_acceptance.py"], source, env)
            return
        # Import tests only after moving to the private source copy. The suite is
        # explicit: historical hook/installer tests exercise a superseded product
        # contract and must not masquerade as V1 installer acceptance.
        suite_names = (["test_real_core.py", "test_v1_runtime_real.py", "test_v1_ux.py"] if args.real_core else
                       args.pattern or ["test_v1*.py", "test_controller.py", "test_console.py",
                        "test_tasks.py", "test_textual.py", "test_health.py",
                        "test_policy_portable.py", "test_rules.py"])
        code = """
import json, os, sys, unittest
sys.path.insert(0, os.getcwd())
suite = unittest.TestSuite()
groups = {}
for pattern in json.loads(sys.argv[1]):
    discovered = unittest.defaultTestLoader.discover('tests', pattern=pattern)
    groups[pattern] = discovered.countTestCases()
    if not groups[pattern]:
        raise SystemExit('required-test-group-empty: ' + pattern)
    suite.addTests(discovered)
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skipped': len(result.skipped), 'success': result.wasSuccessful()}
report.update(json.loads(os.environ.get('MIHOMO_V1_SOURCE_EVIDENCE', '{}')))
report['suites'] = groups
if os.environ.get('MIHOMO_V1_REAL_CORE_REQUIRED') == '1' and result.skipped:
    report['success'] = False
if os.environ.get('MIHOMO_V1_UNIT_REPORT'):
    with open(os.environ['MIHOMO_V1_UNIT_REPORT'], 'w') as stream:
        json.dump(report, stream, sort_keys=True)
raise SystemExit(0 if report['success'] and result.testsRun else 1)
"""
        if args.real_core:
            env["MIHOMO_V1_REAL_CORE_REQUIRED"] = "1"
        if args.report:
            env["MIHOMO_V1_UNIT_REPORT"] = str(args.report.resolve())
        run([sys.executable, "-c", code, json.dumps(suite_names)], source, env)


if __name__ == "__main__":
    main()
