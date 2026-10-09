"""User-level controller component; no global proxy or daemon."""
import json
import os
import re
import stat
try:
    from . import install_support as files
except ImportError:
    import install_support as files
try:
    from .controller_types import ControlError, LIMIT
except ImportError:
    from controller_types import ControlError, LIMIT

def private(path, directory=False):
    path = files.safe_path(path, directory)
    info = path.stat()
    if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ControlError("controller-path-must-be-private-owned-regular")
    return path


def read_config(path):
    if not path.exists() and not path.is_symlink():
        raise ControlError("config-missing")
    try:
        import yaml
    except ImportError:
        raise ControlError("controller-requires-PyYAML-see-control-plane-guide") from None
    private(path)
    if path.stat().st_size > LIMIT:
        raise ControlError("config-too-large")
    text = path.read_bytes().decode("utf-8")
    try:
        # Reject ambiguous merges, aliases and duplicate keys before any edit.
        if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.DocumentEndToken)) for t in yaml.scan(text)):
            raise ControlError("config-anchors-or-document-end-not-supported")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        def check(n):
            if isinstance(n, yaml.MappingNode):
                names = []
                for key, value in n.value:
                    if not isinstance(key, yaml.ScalarNode) or key.value in names or key.value == "<<":
                        raise ControlError("config-duplicate-or-complex-key")
                    names.append(key.value)
                    check(value)
            elif isinstance(n, yaml.SequenceNode):
                for child in n.value:
                    check(child)
        check(node)
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or not isinstance(node, yaml.MappingNode):
            raise ControlError("config-must-be-mapping")
        return text, data, node
    except (yaml.YAMLError, RecursionError):
        raise ControlError("config-yaml-invalid") from None


def patch_config(text, node, changes):
    # Replace whole top-level entries using parser marks; preserve other bytes.
    if node.flow_style:
        raise ControlError("config-needs-block-style-root")
    lines = text.splitlines(keepends=True)
    edits = []
    for key, value in node.value:
        if key.value in changes:
            end = value.end_mark.line + (1 if value.end_mark.column else 0)
            edits.append((key.start_mark.line, end))
    for start, end in sorted(edits, reverse=True):
        del lines[start:end]
    result = "".join(lines).rstrip() + "\n"
    # JSON scalars/containers are a YAML subset; no secret interpolation.
    return result + "".join(k + ": " + json.dumps(v, ensure_ascii=False) + "\n" for k, v in changes.items())


def endpoint(data):
    match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", str(data.get("external-controller", "")))
    token = data.get("secret")
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise ControlError("controller-not-configured-as-loopback")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ControlError("controller-secret-must-be-32-to-256-url-safe-characters")
    if any(data.get(k) for k in ("external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-doh-server")):
        raise ControlError("additional-controller-listeners-not-supported")
    return int(match[1]), token
