"""Read and rewrite a note's frontmatter without touching its body. Shared by file-notes and note-outcome.

Iron rule: the body's md5 is checked before and after, and a mismatch aborts. Values keep their types and order
(dates stay dates). A change made by anyone else between the read and the rename aborts too.
"""
import os
from pathlib import Path

import yaml

import _ingest_keys


class NoteError(Exception):
    """This note cannot be used. It fails its own thought only; it never aborts a run."""


def split(text):
    """(frontmatter text, raw remainder after the closing fence), or (None, text) if there is no frontmatter."""
    if not text.startswith('---\n'):
        return None, text
    end = text.find('\n---\n', 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5:]


def body_of(text):
    _, rest = split(text)
    return rest.lstrip('\n')


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


def read(path):
    """(text, stamp) for a note; the stamp is what rewrite compares against."""
    p = Path(path)
    st = p.stat()
    return p.read_text(encoding='utf-8'), (st.st_mtime_ns, st.st_size)


def rewrite(path, text, stamp, data):
    """Replace the frontmatter with data. Raises NoteError if the body would change or the file already has."""
    _, rest = split(text)
    new = '---\n' + dump(data) + '---\n' + rest
    if _ingest_keys.body_md5(body_of(new)) != _ingest_keys.body_md5(body_of(text)):
        raise NoteError('body md5 changed; nothing written')
    if yaml.safe_load(split(new)[0]) != data:
        raise NoteError('frontmatter does not survive a round trip; nothing written')
    p = Path(path)
    tmp = p.with_name(f'.{p.name}.tmp')
    try:
        tmp.write_text(new, encoding='utf-8')
        st = p.stat()
        if (st.st_mtime_ns, st.st_size) != stamp:
            raise NoteError('note changed while this script was running; nothing written')
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()
