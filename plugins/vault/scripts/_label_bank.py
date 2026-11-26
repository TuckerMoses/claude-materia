"""The label bank and the note-label rewrite, as library code. Shared by label-bank and relabel-notes.

Nothing here writes: every function returns _vault_tx.Change objects, and the caller lands them in one transaction.
That is how a rename puts the bank entry, every note, routing rules and source lenses in one commit (D11).
"""
import json
import sys
from pathlib import Path

import jsonschema
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(1, str(HERE.parent / 'skills' / 'ingest' / 'scripts'))  # _note_frontmatter, _ingest_keys

import _ingest_keys  # noqa: E402
import _note_frontmatter as fm  # noqa: E402
import _vault_tx as tx  # noqa: E402

BANK = '_machine/labels.yml'
ROUTING = '_machine/routing.yml'
SOURCES = '_machine/ingest_paths.yml'
SCHEMA = json.loads((HERE / 'labels.schema.json').read_text(encoding='utf-8'))


class BankError(Exception):
    """Refused. Nothing changed."""


class _Folding(yaml.SafeDumper):
    pass


def _str(dumper, value):
    style = '>' if len(value) > 60 and '\n' not in value and value == value.strip() else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


_Folding.add_representer(str, _str)


def dump(data, fold=False):
    """Key order kept. FOLD writes long one-line strings as `>-` blocks, the seed bank's style, falling back to
    plain safe_dump whenever that would not read back identically."""
    opts = dict(sort_keys=False, allow_unicode=True, default_flow_style=False, width=90)
    if fold:
        out = yaml.dump(data, Dumper=_Folding, **opts)
        if yaml.safe_load(out) == data:
            return out
    return yaml.safe_dump(data, **opts)


def validate(data):
    error = jsonschema.exceptions.best_match(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))
    if error is not None:
        where = '/'.join(str(p) for p in error.absolute_path) or '(root)'
        raise BankError(f'bank fails its schema at {where}: {error.message}')


def header(text):
    """The leading comment block, kept across rewrites. Comments elsewhere do not survive."""
    lines = []
    for line in text.splitlines(keepends=True):
        if line.startswith('#') or not line.strip():
            lines.append(line)
        else:
            break
    head = ''.join(lines).rstrip('\n')
    return head + '\n\n' if head else ''


class Bank:
    """The bank as read: its text and stamp, for the write; its data, for everything else."""

    def __init__(self, vault):
        path = Path(vault) / BANK
        if not path.is_file():
            raise BankError(f'no label bank at {BANK}')
        self.text, self.stamp = tx.read(path)
        try:
            self.data = yaml.safe_load(self.text)
        except yaml.YAMLError as e:
            raise BankError('bank does not parse: ' + ' '.join(str(e).split())[:160])
        validate(self.data)
        self.labels = self.data['labels']

    def entry(self, name):
        if name not in self.labels:
            raise BankError(f'no label named {name}')
        return self.labels[name]

    def active(self, name):
        return name in self.labels and self.labels[name]['status'] == 'active'

    def change(self, labels):
        """A Change replacing the bank's labels with LABELS (an ordered dict), validated before and after the write."""
        data = dict(self.data, labels=labels)
        validate(data)
        new = header(self.text) + dump(data, fold=True)
        if yaml.safe_load(new) != data:
            raise BankError('bank does not survive a round trip; nothing written')

        def check(back):
            validate(yaml.safe_load(back))
        return tx.Change(BANK, self.text, self.stamp, new, check)


def refuse_unless_owned(name, entry, op, protected_too=True):
    if entry.get('origin') == 'imported':
        raise BankError(f'{name} is imported; the vault does not {op} it')
    if protected_too and entry.get('protected'):
        raise BankError(f'{name} is protected; {op} is refused')


# --- notes -----------------------------------------------------------------------------------------------------

def note_path(vault, slug):
    if not isinstance(slug, str) or not slug or '/' in slug or '\\' in slug or slug.startswith('.'):
        raise BankError(f'not a note slug: {slug!r}')
    return Path(vault) / 'notes' / f'{slug}.md'


def labels_of(data, slug):
    labels = data.get('labels')
    if labels is None:
        return []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise BankError(f'{slug}: labels is not a list of strings')
    return labels


def note_change(vault, slug, relabel):
    """A Change setting a note's labels to relabel(current), or None if that changes nothing. Frontmatter only:
    the body's md5 is checked when the text is rendered and again on the text read back after the write."""
    path = note_path(vault, slug)
    if not path.is_file():
        raise BankError(f'no note named {slug}')
    try:
        text, stamp = tx.read(path)
        data = fm.parse(text)
        current = labels_of(data, slug)
        new_labels = relabel(list(current))
        if new_labels == current:
            return None
        data['labels'] = new_labels
        new = fm.render(text, data)
    except (fm.NoteError, OSError, UnicodeDecodeError) as e:
        raise BankError(f'{slug}: {e}')
    before = _ingest_keys.body_md5(fm.body_of(text))

    def check(back):
        after = _ingest_keys.body_md5(fm.body_of(back))
        if after != before:
            raise BankError(f'{slug}: body md5 changed on write (before {before}, after {after})')
    return tx.Change(f'notes/{path.name}', text, stamp, new, check)


def carriers(vault, name):
    """Slugs of every note in notes/ whose labels include NAME. A note that cannot be read and mentions NAME at all
    is an error: it might carry it, and a rename or remove must not guess."""
    found, unreadable = [], []
    for p in sorted((Path(vault) / 'notes').glob('*.md')):
        try:
            text = fm.read_text(p)
        except (OSError, UnicodeDecodeError):
            unreadable.append(p.stem)
            continue
        try:
            if name in labels_of(fm.parse(text), p.stem):
                found.append(p.stem)
        except (fm.NoteError, BankError):
            if name in text:
                unreadable.append(p.stem)
    if unreadable:
        raise BankError(f'cannot tell whether these notes carry {name}: {", ".join(unreadable)}')
    return found


# --- routing rules and source lenses ---------------------------------------------------------------------------

def _sub(node, old, new):
    """NODE (a rule's match: strings, lists, {any|none: [...]}) with every exact OLD replaced by NEW. Wildcards
    such as `project:*` name no single label and are left alone."""
    if isinstance(node, str):
        return new if node == old else node
    if isinstance(node, list):
        return [_sub(x, old, new) for x in node]
    if isinstance(node, dict):
        return {k: _sub(v, old, new) for k, v in node.items()}
    return node


def _routing(data, old, new):
    for rule in (data or {}).get('rules') or []:
        if isinstance(rule, dict) and 'match' in rule:
            rule['match'] = _sub(rule['match'], old, new)
    return data


def _sources(data, old, new):
    for source in (data or {}).get('sources') or []:
        if isinstance(source, dict) and isinstance(source.get('lens'), list):
            source['lens'] = [new if x == old else x for x in source['lens']]
    return data


REFERENCES = ((ROUTING, _routing), (SOURCES, _sources))


def reference_changes(vault, old, new):
    """Changes renaming OLD to NEW in routing rules and source lenses. An absent file has nothing to rewrite."""
    changes = []
    for rel, rewrite in REFERENCES:
        path = Path(vault) / rel
        if not path.is_file():
            continue
        text, stamp = tx.read(path)
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise BankError(f'{rel} does not parse: ' + ' '.join(str(e).split())[:160])
        before = yaml.safe_load(text)
        after = rewrite(data, old, new)
        if after == before:
            continue
        out = header(text) + dump(after)
        if yaml.safe_load(out) != after:
            raise BankError(f'{rel} does not survive a round trip; nothing written')
        changes.append(tx.Change(rel, text, stamp, out))
    return changes


def referenced_by(vault, name):
    """Which of routing.yml and ingest_paths.yml name NAME exactly."""
    sentinel = 'NOT A LABEL'
    return [c.rel for c in reference_changes(vault, name, sentinel)]


# --- merge and dry runs ----------------------------------------------------------------------------------------

def _dedupe(node, label):
    """NODE with repeats of LABEL dropped from every list. A merge can turn `{any: [A, B]}` into `{any: [B, B]}`;
    every list in a match or a lens is a set, so the repeat says nothing."""
    if isinstance(node, list):
        out, seen = [], False
        for x in node:
            if x == label:
                if seen:
                    continue
                seen = True
            out.append(_dedupe(x, label))
        return out
    if isinstance(node, dict):
        return {k: _dedupe(v, label) for k, v in node.items()}
    return node


_FIELDS = {ROUTING: ('rules', 'match'), SOURCES: ('sources', 'lens')}


def merge_reference_changes(vault, old, new):
    """reference_changes(OLD -> NEW) with NEW deduplicated in each rewritten match and lens, for a merge, where
    NEW may already sit beside OLD."""
    out = []
    for c in reference_changes(vault, old, new):
        data = yaml.safe_load(c.new)
        key, field = _FIELDS[c.rel]
        for item in data.get(key) or []:
            if isinstance(item, dict) and field in item:
                item[field] = _dedupe(item[field], new)
        text = header(c.old) + dump(data)
        if yaml.safe_load(text) != data:
            raise BankError(f'{c.rel} does not survive a round trip; nothing written')
        out.append(tx.Change(c.rel, c.old, c.stamp, text))
    return out


def reference_edits(changes):
    """Per routing rule and per source that CHANGES alter: where it sits and its match or lens before and after.
    What a dry run shows the human."""
    edits = []
    for c in changes:
        if c.rel not in _FIELDS:
            continue
        key, field = _FIELDS[c.rel]
        before = (yaml.safe_load(c.old) or {}).get(key) or []
        after = (yaml.safe_load(c.new) or {}).get(key) or []
        for i, (b, a) in enumerate(zip(before, after)):
            if b != a and isinstance(b, dict) and isinstance(a, dict):
                edit = {'file': c.rel, 'index': i, 'field': field, 'before': b.get(field), 'after': a.get(field)}
                if 'path' in b:
                    edit['path'] = b['path']
                edits.append(edit)
    return edits


def note_labels_change(change):
    """(before, after) labels of a note Change."""
    slug = Path(change.rel).stem
    return labels_of(fm.parse(change.old), slug), labels_of(fm.parse(change.new), slug)
