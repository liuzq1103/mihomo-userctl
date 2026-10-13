"""Explicit, private, hash-locked optional Textual environment."""
import hashlib
import http.client
import os
from pathlib import Path
import subprocess
import sys
import tempfile

try:
    from .controller_types import ControlError
    from . import install_support as files
except ImportError:
    from controller_types import ControlError
    import install_support as files

PIP_WHEEL = "pip-25.2-py3-none-any.whl"
PIP_HASH = "6d67a2b4e7f14d8b31b8b52648866fa717f45a1eb70e83002f4331d07e953717"
PIP_PATH = "/packages/b7/3f/945ef7ab14dc4f9d7f40288d2df998d1837ee0888ec3659c813487572faa/" + PIP_WHEEL


def interpreter():
    root = Path(__file__).resolve().parent
    environment = root / "textual-env"
    if (root / "installation.json").exists():
        record = files.owned_json(root / "installation.json")
        files.verify_generation(record)
        if record.get("textual_environment"):
            environment = Path(record["textual_environment"]["path"])
    executable = environment / "bin/python"
    if executable.exists():
        files.safe_path(environment, True)
        if environment.stat().st_mode & 0o077:
            raise ControlError("unsafe-textual-environment")
        files.safe_path(executable)
        return executable, environment
    return None, None


def launch(arguments, module="controller.py", require_textual=True):
    root = Path(__file__).resolve().parent
    try:
        executable, environment = interpreter()
    except (files.InstallError, ControlError, OSError, ValueError, KeyError, TypeError):
        if require_textual:
            raise
        # An unusable optional environment must not remove the base CLI or
        # curses/plain fallback. No code from that environment is executed.
        executable, environment = None, None
    if executable:
        if require_textual and Path(sys.prefix).resolve() == environment.resolve():
            return
        os.execv(str(executable), [str(executable), "-B", str(root / module)] + list(arguments))
    if not require_textual:
        os.execv(sys.executable, [sys.executable, "-B", str(root / module)] + list(arguments))
    # A developer's explicitly selected Python may already provide Textual.
    try:
        import textual  # noqa: F401
    except ImportError:
        raise ControlError("textual-not-installed-use-engine-curses-or-install-with-textual") from None


def install(generation, interpreter, wheelhouse=None):
    root = files.safe_path(Path(generation).absolute(), True)
    environment = root / "textual-env"
    if environment.exists():
        raise ControlError("textual-environment-already-exists")
    result = subprocess.run([interpreter, "-c", "import sys; sys.exit(sys.version_info < (3,9))"], timeout=10)
    if result.returncode:
        raise ControlError("textual-requires-python-3.9-or-newer")
    previous = os.umask(0o077)
    # Package tools must not inherit proxy credentials, Python import hooks or
    # account-specific index settings from an interactive shell.
    environment_vars = {key: value for key, value in os.environ.items()
                        if key.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
                        and not key.startswith(("MIHOMO_", "PYTHON", "PIP_"))}
    try:
        # --without-pip also works on distributions that omit ensurepip. The
        # bootstrap wheel is pinned, checked and run only inside this new venv.
        subprocess.run([interpreter, "-I", "-m", "venv", "--copies", "--without-pip", str(environment)], env=environment_vars, check=True, timeout=90)
        with tempfile.TemporaryDirectory(prefix="pip-bootstrap-", dir=root) as temporary:
            wheel = Path(temporary) / PIP_WHEEL
            if wheelhouse:
                wheels = files.safe_path(Path(wheelhouse).absolute(), True)
                body = files.safe_path(wheels / PIP_WHEEL).read_bytes()
            else:
                connection = http.client.HTTPSConnection("files.pythonhosted.org", timeout=30)
                try:
                    connection.request("GET", PIP_PATH)
                    response = connection.getresponse()
                    if response.status != 200:
                        raise ControlError("pip-bootstrap-download-failed")
                    body = response.read(8 * 1024 * 1024 + 1)
                finally:
                    connection.close()
            if hashlib.sha256(body).hexdigest() != PIP_HASH:
                raise ControlError("pip-bootstrap-hash-mismatch")
            files.atomic_bytes(wheel, body)
            code = "import sys; sys.path.insert(0, sys.argv.pop(1)); from pip._internal.cli.main import main; sys.exit(main())"
            arguments = [str(environment / "bin/python"), "-I", "-c", code, str(wheel), "--isolated", "install",
                     "--disable-pip-version-check", "--no-cache-dir", "--require-hashes",
                     "--only-binary=:all:", "-r", str(root / "textual-requirements.txt")]
            if wheelhouse:
                arguments.extend(["--no-index", "--find-links", str(wheels)])
            subprocess.run(arguments, env=environment_vars, check=True, timeout=240)
        subprocess.run([str(environment / "bin/python"), "-I", "-m", "pip", "check"], env=environment_vars, check=True, timeout=30)
    finally:
        os.umask(previous)


def register(generation, backup):
    root = files.safe_path(Path(generation), True)
    transaction = files.owned_json(Path(backup) / "transaction.json")
    if transaction["generation"] != root.name:
        raise ControlError("textual-generation-mismatch")
    record = files.owned_json(root / "installation.json")
    record["textual_environment"] = {"path": str(root / "textual-env"),
                                     "lock_sha256": files.digest(root / "textual-requirements.txt")}
    files.verify_generation(record)
    transaction["record"] = record
    files.write_json(root / "installation.json", record)
    files.write_json(Path(backup) / "transaction.json", transaction)


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["--run"]:
            if len(sys.argv) < 3 or sys.argv[2] not in ("controller.py", "controller_runtime.py"):
                raise ControlError("invalid-controller-entry")
            launch(sys.argv[3:], module=sys.argv[2], require_textual=False)
        elif sys.argv[1:2] == ["--register"]:
            register(*sys.argv[2:])
        else:
            install(*sys.argv[1:])
    except (ControlError, files.InstallError, OSError, subprocess.SubprocessError) as error:
        print("mihomoctl: " + getattr(error, "code", "optional-textual-install-failed"), file=sys.stderr)
        sys.exit(2)
