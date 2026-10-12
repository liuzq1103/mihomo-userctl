"""Strict YAML loading.

Security rules:
- Anchors and aliases are rejected on the token stream before parsing.
- Duplicate mapping keys are rejected during construction.
- Errors never echo input text (YAML error messages include source
  context); only stable codes with line/column are reported.
"""

from pathlib import Path

import yaml

from .errors import ConfigError


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError:
            raise ConfigError("config-invalid", "unhashable YAML key at line %d" % _node_line(key_node)) from None
        if duplicate:
            mark = getattr(key_node, "start_mark", None)
            column = (mark.column + 1) if mark else 0
            raise ConfigError("config-invalid", "duplicate YAML key at line %d column %d" % (_node_line(key_node), column))
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


def _node_line(node):
    mark = getattr(node, "start_mark", None)
    return (mark.line + 1) if mark else 0


def _mark(exc):
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is not None:
        return mark.line + 1, mark.column + 1
    return 0, 0


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
_StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _reject_anchor_tokens(text):
    """Scan the token stream and refuse anchors/aliases/merge keys."""
    try:
        for token in yaml.scan(text):
            if isinstance(token, (yaml.AnchorToken, yaml.AliasToken)):
                line, column = _mark(token)
                raise ConfigError("config-invalid",
                                  "YAML anchors/aliases are not allowed (line %d column %d)" % (line, column))
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        line, column = _mark(exc)
        raise ConfigError("config-invalid", "YAML syntax error (line %d column %d)" % (line, column)) from None


def strict_load_all(text):
    """Parse all YAML documents strictly; returns a list."""
    if "\x00" in text:
        raise ConfigError("config-invalid", "NUL byte in YAML document")
    _reject_anchor_tokens(text)
    try:
        return list(yaml.load_all(text, Loader=_StrictLoader))
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        line, column = _mark(exc)
        raise ConfigError("config-invalid", "YAML error (line %d column %d)" % (line, column)) from None


def strict_load(text):
    """Parse exactly one YAML document strictly."""
    documents = strict_load_all(text)
    if len(documents) != 1:
        raise ConfigError("config-invalid", "expected exactly one YAML document")
    return documents[0]


def read_private_yaml(path, code="config-invalid"):
    """Trust-check then strictly parse a private YAML file."""
    from .trust import require_private_file
    require_private_file(path, code=code)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(code, "unreadable: %s" % path) from None
    if len(text) > 4 * 1024 * 1024:
        raise ConfigError(code, "file too large: %s" % path)
    return strict_load(text)
