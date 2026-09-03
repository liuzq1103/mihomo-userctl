#!/usr/bin/env python3
"""Version-pinned self update. Network/data errors never echo upstream payloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

sys.dont_write_bytecode = True

try:
    from . import install_support as installer
except ImportError:
    import install_support as installer

REPO = "liuzq1103/mihomo-userctl"
API = "https://api.github.com/repos/" + REPO
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA = re.compile(r"[a-f0-9]{40}$")
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024


class UpdateError(Exception):
    def __init__(self, message, code=1):
        self.code = code
        super().__init__(message)


def emit(status, item, evidence):
    print("{}\t{}\t{}".format(status, item, evidence), flush=True)


def version(tag):
    match = TAG.fullmatch(tag)
    if match is None:
        raise UpdateError("use-a-published-stable-vX.Y.Z-tag", 2)
    return tuple(int(number) for number in match.groups())


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in ("api.github.com", "codeload.github.com")
                or parsed.username or parsed.password):
            raise UpdateError("non-official-download-redirect-rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHub:
    def __init__(self):
        self.opener = urllib.request.build_opener(OfficialRedirect())

    def get(self, url, limit):
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "mihomo-userctl-update/1"})
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read(limit + 1)
            if len(body) > limit:
                raise UpdateError("download-size-limit-exceeded")
            return body
        except UpdateError:
            raise
        except Exception:
            raise UpdateError("official-source-request-failed-no-active-files-changed") from None

    def api(self, suffix):
        try:
            return json.loads(self.get(API + suffix, 2 * 1024 * 1024))
        except (ValueError, TypeError):
            raise UpdateError("invalid-official-api-response") from None

    def resolve(self, tag=None):
        if tag is not None:
            version(tag)
        release = self.api("/releases/latest" if tag is None else "/releases/tags/" + tag)
        tag = release.get("tag_name")
        version(tag if isinstance(tag, str) else "")
        if (release.get("draft") is not False or release.get("prerelease") is not False
                or not release.get("published_at") or not isinstance(release.get("id"), int)):
            raise UpdateError("target-is-not-a-published-stable-release", 2)
        obj = self.api("/git/ref/tags/" + tag)["object"]
        for _ in range(8):
            sha = obj.get("sha", "")
            if not SHA.fullmatch(sha):
                raise UpdateError("invalid-tag-object")
            if obj.get("type") == "commit":
                return {"kind": "github-release-source", "repository": REPO, "tag": tag,
                        "commit": sha, "release_id": release["id"],
                        "archive_url": "https://codeload.github.com/" + REPO + "/zip/" + sha,
                        "verification": "HTTPS-GitHub-tag-to-commit;no-independent-archive-digest-or-signature",
                        "official_digest": None}
            if obj.get("type") != "tag":
                break
            obj = self.api("/git/tags/" + sha)["object"]
        raise UpdateError("unsupported-or-cyclic-tag-object")

    def archive(self, source, destination):
        body = self.get(source["archive_url"], MAX_ARCHIVE)
        installer.atomic_bytes(destination, body)
        source["archive_sha256"] = hashlib.sha256(body).hexdigest()


def extract(archive, destination):
    """Reject traversal, links, devices, collisions, bombs, and multiple roots."""
    try:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if not entries or len(entries) > 5000 or sum(i.file_size for i in entries) > MAX_EXPANDED:
                raise UpdateError("archive-expansion-limit-exceeded")
            roots, seen = set(), set()
            for entry in entries:
                raw = entry.filename
                path = PurePosixPath(raw)
                mode = entry.external_attr >> 16
                if ("\\" in raw or ":" in raw or any(ord(c) < 32 for c in raw)
                        or path.is_absolute() or ".." in path.parts or not path.parts
                        or entry.flag_bits & 1
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise UpdateError("unsafe-archive-member")
                normalized = str(path).casefold()
                if normalized in seen:
                    raise UpdateError("duplicate-archive-member")
                seen.add(normalized)
                roots.add(path.parts[0])
            if len(roots) != 1:
                raise UpdateError("archive-must-have-one-source-root")
            for entry in entries:
                target = destination.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():
                    target.mkdir(parents=True, mode=0o700, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    installer.atomic_bytes(target, package.read(entry), 644)
            return destination / roots.pop()
    except UpdateError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise UpdateError("invalid-or-incomplete-source-archive") from None


def validate(source, tag):
    try:
        manifest = json.loads((source / "release-manifest.json").read_text())
        expected = {"format": 1, "version": tag[1:], "update_protocol": 1,
                    "validation_profile": "installation-v1"}
        if manifest != expected:
            raise UpdateError("target-does-not-support-update-protocol-1", 2)
        required = list(installer.RUNTIME) + ["install.sh", "examples/bashrc-loader.bash",
                    "tests/test.sh", "tests/docs-test.sh", "tests/secret-scan.sh", "tests/audit-test.sh",
                    "tests/test_acceptance.py"]
        if any(not (source / name).is_file() for name in required):
            raise UpdateError("target-release-is-incomplete", 2)
        for file, pattern in (("install.sh", r"^VERSION=([^\n]+)$"),
                              ("src/common.bash", r'^MIHOMO_USERCTL_VERSION="([^"]+)"$')):
            match = re.search(pattern, (source / file).read_text(), re.M)
            if match is None or match[1] != tag[1:]:
                raise UpdateError("target-version-markers-disagree", 2)
    except (OSError, ValueError):
        raise UpdateError("target-manifest-missing-or-invalid", 2) from None
    # Released source tests run with a disposable HOME, never live credentials.
    with tempfile.TemporaryDirectory(prefix="validation-", dir=source.parent) as home:
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + "/.config",
                   XDG_DATA_HOME=home + "/.local/share", PYTHONDONTWRITEBYTECODE="1")
        for key in list(env):
            if key.startswith("MIHOMO_") or key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
                env.pop(key)
        commands = [["bash", "-n", str(p)] for p in source.rglob("*")
                    if p.is_file() and (p.suffix in (".sh", ".bash") or p.name == "mihomoctl")]
        commands += [["bash", "tests/test.sh"],
                     [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_acceptance.py"],
                     ["bash", "tests/audit-test.sh"], ["bash", "tests/docs-test.sh"],
                     ["bash", "tests/secret-scan.sh"]]
        for command in commands:
            try:
                proc = subprocess.run(command, cwd=source, env=env, capture_output=True, timeout=180)
            except (OSError, subprocess.TimeoutExpired):
                raise UpdateError("target-validation-tool-failed") from None
            if proc.returncode:
                raise UpdateError("target-validation-failed-no-active-files-changed")
    emit("PASS", "target-validation", "installation-v1;syntax-install-shell-acceptance-audit-docs-secret-patterns")


def settings(record):
    generation = Path(record["install_root"])
    if record.get("generation"):
        generation = generation / "generations" / record["generation"]
    program = ('source "$1"; _muc_load_config || exit 2; _muc_load_credentials || exit 2; '
               'printf "%s\\0" "$MIHOMO_SERVICE" "$MIHOMO_PORT" "$MIHOMO_READY_URL" '
               '"$MIHOMO_HTTP_PROXY" "$MIHOMO_HTTPS_PROXY" "$MIHOMO_ALL_PROXY"')
    env = dict(os.environ, HOME=record["home"], XDG_CONFIG_HOME=record["config_home"],
               MIHOMO_USERCTL_CONFIG=str(Path(record["config_home"]) / "mihomo/mihomo-shell.conf"),
               MIHOMO_USERCTL_CREDENTIALS=str(Path(record["config_home"]) / "mihomo/client.env"))
    proc = subprocess.run(["bash", "-c", program, "_", str(generation / "common.bash")],
                          env=env, capture_output=True, timeout=10)
    values = proc.stdout.decode().split("\0")
    if proc.returncode or len(values) != 7:
        raise UpdateError("installed-configuration-or-credentials-invalid", 2)
    return dict(zip(("MIHOMO_SERVICE", "MIHOMO_PORT", "MIHOMO_READY_URL", "MIHOMO_HTTP_PROXY",
                     "MIHOMO_HTTPS_PROXY", "MIHOMO_ALL_PROXY"), values[:6]))


def service_state(service):
    result = []
    for query in ("is-active", "is-enabled"):
        proc = subprocess.run(["systemctl", "--user", query, service], capture_output=True, text=True, timeout=10)
        value = proc.stdout.strip()
        valid = ({"active": (0,), "inactive": (3,), "failed": (3,)} if query == "is-active" else
                 {"enabled": (0,), "enabled-runtime": (0,), "disabled": (1,),
                  "static": (0,), "indirect": (0,), "masked": (1,), "masked-runtime": (1,)})
        if value not in valid or proc.returncode not in valid[value]:
            raise UpdateError("service-state-cannot-be-established", 2)
        result.append(value)
    return tuple(result)


def preserved(record):
    config = Path(record["config_home"])
    result = {}
    for path in (config / "mihomo/mihomo-shell.conf", config / "mihomo/client.env", config / "mihomo/config.yaml"):
        result[str(path)] = (installer.digest(path), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
    text = Path(record["bashrc"]).read_text()
    result["startup-outside-loader"] = text.replace(installer.loader_block(record["bashrc"]), "")
    return result


def apply(source, source_record, record, config, fd):
    env = dict(os.environ, HOME=record["home"], XDG_CONFIG_HOME=record["config_home"],
               XDG_DATA_HOME=record["data_home"], MIHOMO_INSTALL_LOCK_FD=str(fd))
    before = preserved(record)
    state = service_state(config["MIHOMO_SERVICE"])
    provenance = source.parent / "verified-source.json"
    installer.write_json(provenance, source_record)
    proc = subprocess.run(["bash", str(source / "install.sh"), "--bashrc", record["bashrc"],
                           "--source-record", str(provenance), "--preserve-service-state"],
                          env=env, pass_fds=(fd,), capture_output=True, text=True)
    # Only parse an installer-owned backup path, never echo arbitrary output.
    backups = [line[7:] for line in proc.stdout.splitlines() if line.startswith("backup=")]
    if not backups:
        pending = Path(record["install_root"]) / "pending-install.json"
        if pending.exists():
            backups = [installer.owned_json(pending)["backup"]]
    if backups:
        emit("PASS", "backup", backups[-1])
        emit("UNVERIFIED", "rollback-command", "python3 " + shlex.quote(backups[-1] + "/restore.py") +
             " rollback " + shlex.quote(backups[-1]))
    if proc.returncode:
        emit("FAIL", "files-installed", "installer-failed")
        if backups:
            result = Path(backups[-1]) / "result.json"
            restored = result.exists() and installer.owned_json(result).get("files") == "ROLLED_BACK"
            emit("PASS" if restored else "UNVERIFIED", "rollback", "restored" if restored else "inspect-private-backup")
        report_actual(record["install_root"])
        raise UpdateError("update-installation-failed")
    try:
        new = installer.metadata(record["install_root"])
        installer.verify_installed(new)
        if (new["version"] != source_record["tag"][1:] or new["source"].get("commit") != source_record["commit"]
                or before != preserved(record) or state != service_state(config["MIHOMO_SERVICE"])):
            raise UpdateError("final-invariants-failed")
    except (UpdateError, installer.InstallError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        emit("FAIL", "final-check", "installed-version-integrity-settings-or-service-state-mismatch")
        try:
            if not backups:
                raise installer.InstallError("missing-backup")
            installer.rollback(Path(backups[-1]))
        except (installer.InstallError, OSError, ValueError, KeyError):
            emit("UNVERIFIED", "rollback", "incomplete-or-post-update-edits;inspect-private-backup")
        report_actual(record["install_root"])
        raise UpdateError("final-check-failed;service-not-touched-by-updater") from None
    emit("PASS", "files-installed", "version=" + new["version"] + ";commit=" + new["source"]["commit"])
    emit("PASS", "personal-settings", "config-credentials-port-service-startup-content-preserved")
    emit("PASS", "service-state", "active=" + state[0] + ";enabled=" + state[1])
    acceptance_failed = False
    if state[0] == "active":
        runtime = Path(new["install_root"]) / "generations" / new["generation"]
        try:
            acceptance = subprocess.run([sys.executable, str(runtime / "acceptance.py"),
                                          "--expect-enabled", state[1]],
                                        env=dict(os.environ, **config), capture_output=True, text=True, timeout=100)
            rows = []
            for line in acceptance.stdout.splitlines():
                fields = line.split("\t")
                # Only the known verifier's fixed vocabulary is reportable.
                if (len(fields) == 3 and fields[0] in ("PASS", "FAIL", "UNVERIFIED", "DEFERRED")
                        and re.fullmatch(r"[a-z0-9-]+", fields[1])
                        and re.fullmatch(r"[a-zA-Z0-9=;.,_-]+", fields[2])):
                    rows.append(fields)
                    print(line, flush=True)
            acceptance_failed = acceptance.returncode == 1 or any(row[0] == "FAIL" for row in rows)
            if not rows or acceptance.returncode not in (0, 1, 2):
                emit("UNVERIFIED", "listener-and-auth", "verifier-did-not-produce-complete-results")
        except (OSError, subprocess.SubprocessError):
            emit("UNVERIFIED", "listener-and-auth", "verifier-unavailable-or-timed-out")
    else:
        emit("UNVERIFIED", "listener-and-auth", "service-was-stopped;not-started-for-validation")
        emit("UNVERIFIED", "proxy-route", "needs-real-target-and-egress-evidence")
    emit("DEFERRED", "new-shell", "open-new-terminal;existing-shell-keeps-loaded-functions")
    emit("DEFERRED", "long-lived-clients", "reconnect-own-Codex-or-VS-Code-then-verify-new-PID")
    emit("FAIL" if acceptance_failed else "UNVERIFIED", "overall-acceptance",
         "files-installed;end-to-end-evidence-still-required")
    if acceptance_failed:
        return 5
    return 3


def report_actual(root):
    try:
        actual = installer.metadata(root)
        emit("PASS", "actual-installed-version", actual["version"])
        emit("PASS" if actual["source"].get("commit") else "UNVERIFIED", "actual-installed-commit",
             actual["source"].get("commit") or "unknown")
    except (installer.InstallError, OSError, ValueError, KeyError):
        emit("UNVERIFIED", "actual-installed-version", "inspect-backup-and-active-pointer")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "FAIL\targuments\tinvalid-update-options-see-help\n")


def main(argv=None, client=None):
    parser = Parser(description="Update only mihomo-userctl from a pinned official stable release.")
    parser.add_argument("--install-root", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--current-version", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--version", metavar="TAG")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if (args.check and (args.version or args.dry_run)) or (not args.check and not args.version):
        raise UpdateError("choose-check-or-explicit-version", 2)
    record = None
    try:
        record = installer.metadata(args.install_root)
    except (installer.InstallError, OSError, ValueError, KeyError, TypeError):
        emit("UNVERIFIED", "installed-source", "unknown;one-time-migration-required")
    emit("PASS", "current-version", record["version"] if record else args.current_version)
    if record:
        emit("PASS" if record["source"].get("commit") else "UNVERIFIED", "installed-source",
             "commit=" + (record["source"].get("commit") or "unknown") + ";kind=" + record["source"]["kind"] +
             ";local-modifications=" + ("yes" if record["source"].get("dirty") else "not-recorded"))
    client = client or GitHub()
    if args.check:
        if record:
            try:
                installer.verify_installed(record)
                emit("PASS", "installed-integrity", "matches-installation-record")
            except (installer.InstallError, OSError, ValueError, KeyError, TypeError):
                emit("UNVERIFIED", "installed-integrity", "local-code-or-loader-differs;review-before-update")
        target = client.resolve()
        newer = version(target["tag"]) > version("v" + (record["version"] if record else args.current_version))
        emit("PASS", "update-check", "latest=" + target["tag"] + ";available=" + ("yes" if newer else "no"))
        emit("UNVERIFIED", "target-compatibility", "checked-by-version-dry-run;not-by-latest-query")
        return 0
    version(args.version)
    if not record:
        raise UpdateError("metadata-missing-use-reviewed-installer-with-explicit-bashrc-and-XDG-paths", 2)
    if version(args.version) < version("v" + record["version"]):
        raise UpdateError("downgrade-refused-use-exact-backup-rollback", 2)
    with installer.locked(record["data_home"]) as fd:
        if installer.metadata(args.install_root)["generation"] != record["generation"]:
            raise UpdateError("installation-changed-run-command-again", 2)
        if (Path(args.install_root) / "pending-install.json").exists():
            raise UpdateError("interrupted-transaction-restore-recorded-backup-first", 2)
        installer.verify_installed(record)
        if record["source"].get("dirty"):
            raise UpdateError("locally-customized-source-install-review-before-migration", 2)
        config = settings(record)
        target = client.resolve(args.version)
        if target["tag"] != args.version:
            raise UpdateError("release-tag-mismatch")
        if record["source"].get("tag") == args.version and record["source"].get("commit") != target["commit"]:
            raise UpdateError("published-tag-moved-refusing-different-commit", 2)
        emit("PASS", "target-source", "tag=" + target["tag"] + ";commit=" + target["commit"])
        emit("PASS", "source-archive", target["archive_url"] + ";release-id=" + str(target["release_id"]))
        if record["source"].get("commit") == target["commit"] and record["source"].get("tag") == args.version:
            emit("PASS", "files-installed", "already-at-exact-release;no-files-replaced")
            emit("UNVERIFIED", "overall-acceptance", "no-op-is-not-end-to-end-validation")
            return 0 if args.dry_run else 3
        temporary = installer.safe_path(Path(record["data_home"]) / "mihomo-userctl-downloads", True)
        temporary.mkdir(parents=True, mode=0o700, exist_ok=True)
        if temporary.stat().st_mode & 0o077:
            raise UpdateError("download-directory-must-be-private", 2)
        with tempfile.TemporaryDirectory(prefix="update-", dir=temporary) as work:
            work = Path(work)
            archive = work / "source.zip"
            client.archive(target, archive)
            emit("PASS", "download-sha256", target["archive_sha256"] + ";calculated-locally")
            emit("UNVERIFIED", "independent-archive-verification", "official-digest-and-signature-not-provided")
            source = extract(archive, work / "source")
            validate(source, args.version)
            if args.dry_run:
                state = service_state(config["MIHOMO_SERVICE"])
                emit("PASS", "dry-run", "no-active-files-or-service-state-changed")
                emit("PASS", "plan", "complete-generation-and-provenance;atomic-current-pointer;managed-loader-only")
                emit("PASS", "generation-files", ",".join(installer.RUNTIME.values()) + ",installation.json")
                emit("PASS", "stable-launcher", record["bin_file"])
                emit("PASS", "install-root", record["install_root"])
                emit("PASS", "startup-file", record["bashrc"])
                emit("PASS", "service-state-to-preserve", "active=" + state[0] + ";enabled=" + state[1])
                emit("UNVERIFIED", "planned-final-checks", "version-hashes-personal-settings-service-state;listener-if-already-active")
                emit("DEFERRED", "planned-client-checks", "new-shell-and-long-lived-client-reconnect")
                emit("PASS", "backup-plan", str(Path(record["data_home"]) / "mihomo-userctl-backups") +
                     ";installer-transaction;restore.py-rollback")
                return 0
            return apply(source, target, record, config, fd)


def cli(argv=None, client=None):
    try:
        return main(argv, client)
    except UpdateError as error:
        emit("FAIL", "update", str(error))
        return error.code
    except installer.InstallError as error:
        emit("FAIL", "update", str(error))
        return 4 if "another-install" in str(error) else 2
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        emit("FAIL", "update", "operation-failed;private-values-suppressed;inspect-local-backup")
        return 1


if __name__ == "__main__":
    sys.exit(cli())
