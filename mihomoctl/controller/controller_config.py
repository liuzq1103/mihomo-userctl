"""User-level controller component; no global proxy or daemon."""
import os
import re
import stat
import math
try:
    from . import files
except ImportError:
    import files
try:
    from .controller_types import ControlError, LIMIT
except ImportError:
    from controller_types import ControlError, LIMIT

def private(path, directory=False):
    path = files.safe_path(path, directory)
    info = path.stat()
    mode = stat.S_IMODE(info.st_mode)
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind:
        raise ControlError("controller-path-must-be-private-owned-regular")
    if info.st_uid == os.getuid() and mode == (0o700 if directory else 0o600):
        return path
    # Managed system layout (mihomoctl V1): root-owned 0600, or 0640 with the
    # dedicated mihomoctl service group so the core can read its config.
    if info.st_uid == 0 and os.geteuid() == 0:
        if mode == (0o700 if directory else 0o600):
            return path
        if not directory and mode == 0o640:
            try:
                import pwd
                if info.st_gid == pwd.getpwnam("mihomoctl").pw_gid:
                    return path
            except KeyError:
                pass
    error = ControlError("controller-path-must-be-private-owned-regular")
    error.safe_detail = 'expected acting-account ownership and mode %s; observed mode %03o' % ('700' if directory else '600', mode)
    raise error


def read_config(path):
    if not path.exists() and not path.is_symlink():
        raise ControlError("config-missing")
    private(path)
    if path.stat().st_size > LIMIT:
        raise ControlError("config-too-large")
    return parse_config(path.read_bytes())


def parse_config(content):
    """Use the same strict parser for a private file or an in-memory download."""
    try:
        import yaml
    except ImportError:
        raise ControlError("controller-requires-PyYAML-see-control-plane-guide") from None
    try:
        text = content.decode('utf-8') if isinstance(content, bytes) else content
    except UnicodeError:
        raise ControlError('config-yaml-invalid') from None
    try:
        # Reject ambiguous merges, aliases and duplicate keys before any edit.
        if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.DocumentEndToken)) for t in yaml.scan(text)):
            raise ControlError("config-anchors-or-document-end-not-supported")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        def check(n):
            if isinstance(n, yaml.MappingNode):
                names = []
                for key, value in n.value:
                    if (not isinstance(key, yaml.ScalarNode) or key.tag != 'tag:yaml.org,2002:str'
                            or key.value in names or key.value == "<<"):
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
    """Patch values in place; never serialize the untouched document.

    Parser end marks for block containers include following comments/whitespace.
    Use the last actual child instead, so editing one section cannot consume
    the next section's heading. Comments inside replaced containers survive as
    standalone comments; unchanged block children keep their original bytes.
    """
    import yaml
    if node.flow_style:
        raise ControlError("config-needs-block-style-root")
    breaks = re.search(r'\r\n|\r|\n', text)
    newline = breaks.group() if breaks else '\n'
    tokens = list(yaml.scan(text))
    protected = [(t.start_mark.index, t.end_mark.index) for t in tokens
                 if isinstance(t, yaml.tokens.ScalarToken)]
    directives = ''.join(text[t.start_mark.index:t.end_mark.index] + newline for t in tokens
                         if isinstance(t, yaml.tokens.DirectiveToken))
    key_tokens = [t for t in tokens if isinstance(t, yaml.tokens.KeyToken)]
    def key_mark(key):
        return max((t.start_mark for t in key_tokens if t.start_mark.index <= key.start_mark.index), key=lambda m:m.index)
    parent_keys = {}
    def remember(n):
        if isinstance(n, yaml.MappingNode):
            for key, child in n.value:
                parent_keys[id(child)] = key
                remember(child)
        elif isinstance(n, yaml.SequenceNode):
            for child in n.value: remember(child)
    remember(node)
    def end(n):
        if isinstance(n, (yaml.MappingNode, yaml.SequenceNode)) and not n.flow_style:
            children = [v for pair in n.value for v in pair] if isinstance(n, yaml.MappingNode) else n.value
            if children:
                return end(children[-1])
        return n.end_mark.index
    def emit(value, column):
        dumped = yaml.safe_dump(value, allow_unicode=True, default_flow_style=False,
                                sort_keys=False, width=2 ** 31 - 1).rstrip("\n")
        if dumped.endswith("\n..."):
            dumped = dumped[:-4]
        return (newline + " " * column).join(dumped.split("\n"))
    def comments(start, stop):
        return [m.group() for m in re.finditer(r"#[^\r\n]*", text[start:stop])
                if not any(a <= start + m.start() < b for a, b in protected)]
    def blank_lines(start, stop):
        result, offset = [], start
        trailing = re.search(r'(?:(?:\r\n|\r|\n)[ \t]*)+$', text[start:stop])
        boundary = start + trailing.start() if trailing else stop
        for line in text[start:stop].splitlines(keepends=True):
            if offset < boundary and not line.strip(' \t\r\n') and not any(a <= offset < b for a, b in protected):
                result.append('')
            offset += len(line)
        return result
    edits = []
    def same(a, b):
        if type(a) is not type(b):
            return False
        if isinstance(a, dict):
            return len(a) == len(b) and all(k in b and same(v, b[k]) for k, v in a.items())
        if isinstance(a, list):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, float) and math.isnan(a) and math.isnan(b):
            return True
        return a == b
    def patch(n, value):
        # A nested fragment may start after indentation; compare using node
        # construction instead of parsing that fragment as a fresh document.
        loader = yaml.SafeLoader("")
        try:
            old = loader.construct_object(n, deep=True)
        finally:
            loader.dispose()
        if same(old, value):
            return
        # A structural edit must also preserve surviving children verbatim.
        # Work with complete entry lines so quotes and inline comments stay
        # attached to an unchanged item when a sibling is inserted/deleted.
        structural_mapping = (isinstance(n, yaml.MappingNode) and isinstance(value, dict)
                              and list(old) != list(value))
        structural_sequence = (isinstance(n, yaml.SequenceNode) and isinstance(value, list)
                               and len(old) != len(value))
        if (structural_mapping or structural_sequence) and not n.flow_style and n.value and value:
            import difflib
            entries = n.value if structural_mapping else list(enumerate(n.value))
            if structural_mapping:
                mapping_marks = [key_mark(key) for key,_child in entries]
                column = mapping_marks[0].column
            else:
                first = entries[0][1].start_mark.index
                entries_tokens = [t for t in tokens if isinstance(t, yaml.tokens.BlockEntryToken)
                                  and n.start_mark.index <= t.start_mark.index <= first]
                column = entries_tokens[0].start_mark.column
                sequence_marks = [t.start_mark for t in tokens if isinstance(t, yaml.tokens.BlockEntryToken)
                                  and t.start_mark.column == column and n.start_mark.index <= t.start_mark.index < end(n)]
            starts = []
            for i,(key, child) in enumerate(entries):
                mark = mapping_marks[i] if structural_mapping else sequence_marks[i]
                line_start = max(text.rfind('\n', 0, mark.index), text.rfind('\r', 0, mark.index)) + 1
                # A sequence child's mark follows its '- ' indicator.
                starts.append(line_start + column)
            stop = end(n)
            tail = re.match(r'[ \t]*(#[^\r\n]*)', text[stop:]) if stop and text[stop-1] not in '\r\n' else None
            if tail: stop += tail.end()
            ends = [starts[i+1]-column if i+1 < len(starts) else stop for i in range(len(starts))]
            chunks = [text[start:ends[i]] for i, start in enumerate(starts)]
            suffix_match = re.search(r'(?:(?:\r\n|\r|\n)[ \t]*)+$', chunks[-1])
            suffix = suffix_match.group() if suffix_match else ''
            # Subsequent starts excluded indentation; normalize that one prefix
            # only. Everything inside a surviving entry remains exact source.
            chunks = [' '*column + chunk for chunk in chunks]
            chosen, used = [], set()
            def edited_entry(i, child, item):
                before = len(edits)
                patch(child, item)
                local = edits[before:]; del edits[before:]
                chunk = text[starts[i]:ends[i]]
                for a,b,replacement in sorted(local, reverse=True):
                    chunk = chunk[:a-starts[i]] + replacement + chunk[b-starts[i]:]
                return ' '*column + chunk
            if structural_mapping:
                index = {key.value: i for i, (key, _) in enumerate(entries)}
                for key, item in value.items():
                    i = index.get(key)
                    if i is not None:
                        chosen.append(edited_entry(i, entries[i][1], item)); used.add(i)
                    else:
                        chosen.append(' '*column + emit({key:item},column))
                # Preserve a terminal clipped scalar without adding a newline
                # to its value. Mapping key order carries no configuration meaning.
                last = entries[-1][1]
                while isinstance(last, (yaml.MappingNode, yaml.SequenceNode)) and last.value and not last.flow_style:
                    last = last.value[-1][1] if isinstance(last, yaml.MappingNode) else last.value[-1]
                if (not text.endswith(('\n','\r')) and isinstance(last, yaml.ScalarNode)
                        and last.style in ('|','>') and entries[-1][0].value in value):
                    position = list(value).index(entries[-1][0].value)
                    chosen.append(chosen.pop(position))
            else:
                fingerprint = lambda item: yaml.safe_dump(item, sort_keys=True, allow_unicode=True)
                matches = difflib.SequenceMatcher(a=[fingerprint(x) for x in old],
                                                  b=[fingerprint(x) for x in value], autojunk=False)
                retained = {b+offset:a+offset for a,b,size in matches.get_matching_blocks() for offset in range(size)}
                for tag,a,stop_a,b,stop_b in matches.get_opcodes():
                    if tag == 'replace':
                        retained.update({b+offset:a+offset for offset in range(min(stop_a-a,stop_b-b))})
                for j, item in enumerate(value):
                    i = retained.get(j)
                    if i is not None:
                        chunk = edited_entry(i, entries[i][1], item); used.add(i)
                        # Parse the edited fragment: original source positions
                        # and scalar values are no longer valid after recursion.
                        prefix = directives + '---' + newline if directives else ''
                        last = yaml.compose(prefix + chunk, Loader=yaml.SafeLoader)
                        while isinstance(last, (yaml.MappingNode, yaml.SequenceNode)) and last.value and not last.flow_style:
                            last = last.value[-1][1] if isinstance(last, yaml.MappingNode) else last.value[-1]
                        if (j < len(value)-1 and not chunk.endswith(('\n','\r'))
                                and isinstance(last, yaml.ScalarNode) and last.style in ('|','>')):
                            # Sequence order is semantic; safely quote only the
                            # terminal scalar whose syntax cannot be followed.
                            loader = yaml.SafeLoader('')
                            try: scalar = loader.construct_object(last, deep=True)
                            finally: loader.dispose()
                            chunk = chunk[:last.start_mark.index-len(prefix)] + emit(scalar,last.start_mark.column)
                        chosen.append(chunk)
                    else: chosen.append(' '*column + emit([item],column))
            detached = [comment for i in range(len(chunks)) if i not in used
                        for comment in comments(starts[i], ends[i])]
            for i in range(len(chunks)):
                if i in used: continue
                offset = starts[i]
                for line in text[starts[i]:ends[i]].splitlines(keepends=True):
                    if not line.strip(' \t\r\n') and not any(a <= offset < b for a,b in protected): detached.append('')
                    offset += len(line)
            chosen = [' '*column+c for c in detached] + chosen
            replacement = ''
            for chunk in chosen:
                if replacement and not replacement.endswith(('\n','\r')): replacement += newline
                replacement += chunk
            replacement = replacement[column:] if replacement.startswith(' '*column) else replacement
            if suffix and not replacement.endswith(suffix): replacement += suffix
            edits.append((starts[0], stop, replacement))
            return
        if isinstance(n, yaml.MappingNode) and not n.flow_style and isinstance(value, dict) \
                and list(old) == list(value):
            for k, v in n.value:
                patch(v, value[k.value])
            return
        if isinstance(n, yaml.SequenceNode) and not n.flow_style and isinstance(value, list) \
                and len(n.value) == len(value):
            for child, item in zip(n.value, value):
                patch(child, item)
            return
        start, stop, column = n.start_mark.index, end(n), n.start_mark.column
        original_column = column
        parent_key = parent_keys.get(id(n))
        if (isinstance(n, yaml.SequenceNode) and not n.flow_style and parent_key is not None
                and column == key_mark(parent_key).column and not (isinstance(value, list) and value)):
            # YAML permits indentless block sequences after mapping keys;
            # empty collections and scalars require an indented value.
            column += 2
        replacement = emit(value, column)
        retained = comments(start, stop) + blank_lines(start, stop)
        trailing = ''
        if isinstance(n, (yaml.MappingNode, yaml.SequenceNode)):
            tail = re.match(r'[ \t]*(#[^\r\n]*)', text[stop:]) if stop and text[stop - 1] not in '\r\n' else None
            if tail:
                trailing = tail[1]
                stop += tail.end()
                if not n.flow_style:
                    retained.append(trailing)
                    trailing = ''
        if retained:
            replacement = (newline + " " * column).join(retained + [replacement])
        # Flow values follow a key on the same line. A block collection must
        # begin on a fresh indented line, while an existing block keeps indent.
        line = re.split(r'\r\n|\r|\n', text[:start])[-1]
        inline_tag = (bool(line.strip()) and any(isinstance(t, yaml.tokens.TagToken) and t.start_mark.index == start for t in tokens))
        if isinstance(value, (dict, list)) and value and (not isinstance(n, (yaml.MappingNode, yaml.SequenceNode)) or n.flow_style or inline_tag):
            indent = len(line) - len(line.lstrip()) + 2
            replacement = newline + " " * indent + emit(value, indent)
            if retained:
                replacement = newline + " " * indent + (newline + " " * indent).join(retained + [emit(value, indent)])
            if trailing:
                replacement = trailing + replacement
        elif trailing:
            replacement += ' ' + trailing
        if text[start:stop].endswith(('\n', '\r')):
            replacement += re.search(r'(?:(?:\r\n|\r|\n)[ \t]*)+$', text[start:stop]).group()
        if column > original_column and not replacement.startswith(newline):
            replacement = ' '*(column-original_column) + replacement
        edits.append((start, stop, replacement))
    existing = set()
    for key, value in node.value:
        existing.add(key.value)
        if key.value in changes:
            patch(value, changes[key.value])
    result = text
    for start, stop, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[stop:]
    missing = {key: value for key, value in changes.items() if key not in existing}
    # A clipped/folded block scalar at EOF without a newline changes value if
    # we append a line boundary. Insert new entries before that final entry.
    last = node.value[-1][1] if node.value else None
    while isinstance(last, (yaml.MappingNode, yaml.SequenceNode)) and last.value and not last.flow_style:
        last = last.value[-1][1] if isinstance(last, yaml.MappingNode) else last.value[-1]
    insert_before_eof = (missing and not text.endswith(('\n', '\r')) and
                         isinstance(last, yaml.ScalarNode) and last.style in ('|', '>'))
    if insert_before_eof:
        current = yaml.compose(result, Loader=yaml.SafeLoader)
        last_key = current.value[-1][0].start_mark.index
        position = max(t.start_mark.index for t in yaml.scan(result)
                       if isinstance(t, yaml.tokens.KeyToken) and t.start_mark.index <= last_key)
        additions = ''.join(emit({key: value}, 0) + newline for key, value in missing.items())
        result = result[:position] + additions + result[position:]
    else:
        for key, value in missing.items():
            if result and not result.endswith(("\n", "\r")):
                result += newline
            result += emit({key: value}, 0) + newline
    # Catch emitter/type regressions before a candidate can reach disk.
    actual = parse_config(result)[1]
    expected = yaml.safe_load(text)
    expected.update(changes)
    if not same(actual, expected):
        raise ControlError("config-patch-semantics-changed")
    return result


def endpoint(data):
    match = re.fullmatch(r"(?:127\.0\.0\.1|\[::1\]|localhost):([0-9]{1,5})", str(data.get("external-controller", "")))
    token = data.get("secret")
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise ControlError("controller-not-configured-as-loopback")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ControlError("controller-secret-must-be-32-to-256-url-safe-characters")
    if any(data.get(k) for k in ("external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-doh-server")):
        raise ControlError("additional-controller-listeners-not-supported")
    return int(match[1]), token
