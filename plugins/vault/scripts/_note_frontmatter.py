"""Read and rewrite a note's frontmatter without touching its body. Shared by the ingest scripts, note-outcome and the
label scripts beside this file.

Iron rule: the body's md5 is checked before and after, and a mismatch aborts. Values keep their types and order
(dates stay dates). A change made by anyone else between the read and the rename aborts too. A note with CRLF fences
is read and written with CRLF; its body is never re-encoded.

A label change (relabel) is minimal: a one-line flow `labels: [...]` is replaced in place and every other byte stays.
Only another shape of `labels` falls back to a full re-dump, which is refused when it would change what any other
key means to a YAML 1.2 reader (`time: 12:30` re-dumped as 750, `on: yes` as `true: true`).
"""
import os
import re
from pathlib import Path

import yaml

import _ingest_keys


class NoteError(Exception):
    """This note cannot be used. It fails its own thought only; it never aborts a run."""


def _newline(text):
    return '\r\n' if text.startswith('---\r\n') else '\n'


def _fences(text):
    nl = _newline(text)
    return '---' + nl, nl + '---' + nl


def split(text):
    """(frontmatter text, raw remainder after the closing fence), or (None, text) if there is no frontmatter."""
    head, close = _fences(text)
    if not text.startswith(head):
        return None, text
    end = text.find(close, len(head))
    if end == -1:
        return None, text
    return text[len(head):end], text[end + len(close):]


def body_of(text):
    fm, rest = split(text)
    if fm is None or _newline(text) == '\n':
        return rest.lstrip('\n')
    while rest.startswith('\r\n'):
        rest = rest[2:]
    return rest


def parse(text):
    """The frontmatter as a dict. Raises NoteError if it is missing or does not parse."""
    fm, _ = split(text)
    if fm is None:
        raise NoteError('no frontmatter')
    try:
        data = yaml.safe_load(fm)
    except yaml.YAMLError as e:
        raise NoteError('frontmatter does not parse: ' + ' '.join(str(e).split())[:120])
    if not isinstance(data, dict):
        raise NoteError('frontmatter is not a mapping')
    return data


def dump(data):
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=10 ** 6)


def read_text(path):
    """A note's text exactly as stored: line endings are part of a verbatim body."""
    with open(path, encoding='utf-8', newline='') as f:
        return f.read()


def read(path):
    """(text, stamp) for a note; the stamp is what rewrite compares against."""
    st = Path(path).stat()
    return read_text(path), (st.st_mtime_ns, st.st_size)


def render(text, data):
    """The note's text with its frontmatter replaced by data. Raises NoteError if the body would change."""
    fm, rest = split(text)
    nl = _newline(text) if fm is not None else '\n'
    new = '---' + nl + dump(data).replace('\n', nl) + '---' + nl + rest
    if _ingest_keys.body_md5(body_of(new)) != _ingest_keys.body_md5(body_of(text)):
        raise NoteError('body md5 changed; nothing written')
    if yaml.safe_load(split(new)[0]) != data:
        raise NoteError('frontmatter does not survive a round trip; nothing written')
    return new


def rewrite(path, text, stamp, data):
    """Replace the frontmatter with data. Raises NoteError if the body would change or the file already has."""
    new = render(text, data)
    p = Path(path)
    tmp = p.with_name(f'.{p.name}.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new)
        st = p.stat()
        if (st.st_mtime_ns, st.st_size) != stamp:
            raise NoteError('note changed while this script was running; nothing written')
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()


# --- label edits -------------------------------------------------------------------------------------------------

class _Core12(yaml.SafeLoader):
    """A YAML 1.2 core-schema reading of scalars: no yes/no/on/off booleans, no sexagesimal or 0-prefixed octal
    numbers. What a re-dump must not change, as a 1.2 reader (Obsidian among them) sees it."""


_BOOL, _INT, _FLOAT = 'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:int', 'tag:yaml.org,2002:float'
_Core12.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag not in (_BOOL, _INT, _FLOAT)]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Core12.add_implicit_resolver(_BOOL, re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$'), list('tTfF'))
_Core12.add_implicit_resolver(_INT, re.compile(r'^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$'), list('-+0123456789'))
_Core12.add_implicit_resolver(
    _FLOAT, re.compile(r'^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?'
                       r'|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$'), list('-+.0123456789'))


def _int12(loader, node):
    s = loader.construct_scalar(node)
    if s.startswith('0o'):
        return int(s[2:], 8)
    if s.startswith('0x'):
        return int(s[2:], 16)
    return int(s, 10)


_Core12.add_constructor(_INT, _int12)


def _core12(fm_text):
    try:
        data = yaml.load(fm_text, Loader=_Core12)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as e:
        raise NoteError('frontmatter does not parse as YAML 1.2: ' + ' '.join(str(e).split())[:120])
    return data if isinstance(data, dict) else {}


def _others(data):
    return {k: v for k, v in data.items() if k != 'labels'}


_LABELS_LINE = re.compile(r'^labels[ \t]*:')


def _in_place(text, labels):
    """TEXT with only its one-line flow `labels: [...]` replaced, or None when labels has any other shape."""
    fm_text, rest = split(text)
    head, close = _fences(text)
    lines = fm_text.split('\n')
    hits = [i for i, line in enumerate(lines) if _LABELS_LINE.match(line)]
    if len(hits) != 1:
        return None
    i = hits[0]
    line = lines[i]
    cr = '\r' if line.endswith('\r') else ''
    value = line[:len(line) - len(cr)].split(':', 1)[1].strip()
    if not (value.startswith('[') and value.endswith(']')):
        return None
    try:
        alone = yaml.safe_load(line)
    except yaml.YAMLError:
        return None
    if alone != {'labels': parse(text).get('labels')}:
        return None
    new_line = dump({'labels': labels}).rstrip('\n')
    if '\n' in new_line:
        return None
    lines[i] = new_line + cr
    return head + '\n'.join(lines) + close + rest


def relabel(text, labels):
    """The note's text with its labels set to LABELS. Raises NoteError rather than change anything else."""
    fm_text, _ = split(text)
    if fm_text is None:
        raise NoteError('no frontmatter')
    before = parse(text)
    want = dict(before, labels=labels)
    new = _in_place(text, labels)
    if new is None:
        new = render(text, want)
        old12, new12 = _others(_core12(fm_text)), _others(_core12(split(new)[0]))
        if old12 != new12:
            keys = sorted({str(k) for k in set(old12) | set(new12) if old12.get(k, KeyError) != new12.get(k, KeyError)})
            raise NoteError(f'labels is not a one-line [list], and rewriting the frontmatter would change '
                            f'{", ".join(keys)}; nothing written (put labels on one line as [a, b])')
    after = parse(new)
    if after.get('labels') != labels or _others(after) != _others(before):
        raise NoteError('label edit did not parse back to the intended labels with every other key unchanged')
    if _others(_core12(split(new)[0])) != _others(_core12(fm_text)):
        raise NoteError('label edit changed another key; nothing written')
    if _ingest_keys.body_md5(body_of(new)) != _ingest_keys.body_md5(body_of(text)) or \
            split(new)[1] != split(text)[1]:
        raise NoteError('body changed; nothing written')
    return new
