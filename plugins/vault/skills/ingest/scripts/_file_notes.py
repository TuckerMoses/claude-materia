"""The vault's note writer, as library code: the `notes` adapter delivers through deliver(); file-notes runs the rest.

  lookup(vault, manifest)  -> {ref: {slug, labels, outcome} | {failed}} for thoughts already filed
  check(vault, manifest)   -> refuses a manifest that reaches outside its bounds or carries an empty body
  deliver(vault, thought)  -> {status: delivered, landed: {slug, path, status, outcome}} | {status: failed, reason}
  rewrite(vault, plan)     -> {rewritten: [...], failed: [{slug, reason}]}
  finish(vault, plan)      -> markers, then watermarks, then moves; writes report.json; returns it

Iron rule: an empty body or an md5 mismatch raises Abort, which stops the run. A note that cannot be used fails only
its own thought. Idempotency: a note is already filed iff an existing note has the same source and the same body.
"""
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(1, str(Path(__file__).resolve().parents[3] / 'scripts'))  # the plugin's shared modules
import _ingest_keys  # noqa: E402
import _note_frontmatter as fm  # noqa: E402


class Abort(Exception):
    """The iron rule or a bounds check refused. The run must stop before any commit point."""


def slugify(title):
    s = re.sub(r'[^a-z0-9]+', '-', title.lower())
    return s[:80].strip('-') or 'untitled'


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_manifest_paths(vault, manifest):
    """Refuse a manifest that reaches outside its bounds, before anything is written.

    The manifest is model-written from captured text, so it is untrusted input: unchecked, an archive move could
    place a file anywhere and a marker could edit any file.
    """
    journal = (vault / 'journal').resolve()
    for rel in manifest.get('mark_ingested', []):
        if not within((vault / rel).resolve(), journal):
            raise Abort(f'mark_ingested path outside journal/: {rel} — nothing committed')
    moves = manifest.get('archive_moves', [])
    if moves:
        import yaml
        data = yaml.safe_load((vault / '_machine' / 'ingest_paths.yml').read_text(encoding='utf-8')) or {}
        roots = [Path(s['path']).expanduser().resolve() for s in data.get('sources') or []
                 if s.get('track') == 'destructive']
        for mv in moves:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(-\d+)?', mv['date']):
                raise Abort(f'archive_moves date is not a date or run-id: {mv["date"]} — nothing committed')
            src = Path(mv['from']).expanduser().resolve()
            if not any(within(src, r) for r in roots):
                raise Abort(f'archive_moves source is not in a registered destructive source: {mv["from"]} — nothing committed')


def filed_index(vault):
    """{(source, body md5): (path, text)} for every note whose source line can be read. Lookup by value, not by name."""
    index = {}
    for p in sorted((vault / 'notes').glob('*.md')):
        try:
            text = fm.read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        head, _ = fm.split(text)
        if head is None:
            continue
        match = re.search(r'^source:\s*(.*?)\s*$', head, re.M)
        if match:
            key = index_key(match.group(1).strip('"\''), fm.body_of(text))
            index.setdefault(key, (p, text))
    return index


def index_key(source, body):
    """Blank lines before a body are not part of it: the note format puts one there. Trailing ones are in the md5."""
    return (source, _ingest_keys.body_md5(body.lstrip('\n')))


def describe(found):
    path, text = found
    data = fm.parse(text)
    labels = data.get('labels') or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise fm.NoteError('labels is not a list of strings')
    return {'slug': path.stem, 'path': f'notes/{path.name}', 'labels': labels, 'outcome': data.get('outcome')}


def as_date(value):
    return datetime.date.fromisoformat(value) if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else value


def note_text(n):
    data = {'title': n['title'], 'labels': n['labels'], 'created': as_date(n['created']), 'captured': as_date(n['captured']),
            'source': n['source']}
    if n.get('related'):
        data['related'] = n['related']
    return '---\n' + fm.dump(data) + '---\n\n' + n['body'].strip('\n') + '\n'


def lookup(vault, manifest):
    index = filed_index(vault)
    out = {}
    for n in manifest.get('notes', []):
        ref = _ingest_keys.thought_ref(n['source'], n['body'])
        found = index.get(index_key(n['source'], n['body']))
        if found:
            try:
                out[ref] = describe(found)
            except fm.NoteError as e:
                out[ref] = {'failed': f'{found[0].name}: {e}'}
    return out


def check(vault, manifest):
    """Everything the run must refuse before its first write: paths out of bounds, an empty body."""
    check_manifest_paths(vault, manifest)
    for n in manifest.get('notes', []):
        if n.get('disposition') not in DIARY and not n['body'].strip():
            raise Abort(f'(iron rule): empty body for "{n["title"]}" — nothing committed')
    return {'checked': True}


DIARY = ('diary', 'diary-only', 'diary_only')


def deliver(vault, thought):
    """File one thought as a note, or find it already filed. Its slug is the thought's id."""
    if not thought['body'].strip():
        raise Abort(f'(iron rule): empty body for "{thought["title"]}" — nothing committed')
    key = index_key(thought['source'], thought['body'])
    index = filed_index(vault)
    if key in index:
        try:
            found = describe(index[key])
        except fm.NoteError as e:
            return {'status': 'failed', 'reason': f'{index[key][0].name}: {e}'}
        return {'status': 'delivered', 'landed': {'slug': found['slug'], 'path': found['path'], 'status': 'skipped',
                                                  'outcome': found['outcome']}}
    notes_dir = vault / 'notes'
    dest, i = notes_dir / f'{slugify(thought["title"])}.md', 2
    while dest.exists():
        dest, i = notes_dir / f'{slugify(thought["title"])}-{i}.md', i + 1
    try:
        with open(dest, 'x', encoding='utf-8', newline='') as f:
            f.write(note_text(thought))
        text = fm.read_text(dest)
    except OSError as e:
        return {'status': 'failed', 'reason': f'{dest.name}: {e.strerror}'}
    before, after = _ingest_keys.body_md5(thought['body'].lstrip('\n')), _ingest_keys.body_md5(fm.body_of(text))
    if before != after:
        raise Abort(f'(iron rule): body verify failed for {dest.name} (before md5 {before}, after md5 {after}) — no watermarks committed')
    return {'status': 'delivered', 'landed': {'slug': dest.stem, 'path': f'notes/{dest.name}', 'status': 'written',
                                              'outcome': None}}


def route_key(entry):
    """What makes two routed_to entries the same delivery, or None if ENTRY is malformed. Entries are {target, adapter};
    older ones are {container, artifact, name}. The vault copy is one delivery whatever its entry calls it."""
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get('target'), str) and isinstance(entry.get('adapter'), str):
        kind, name = entry['adapter'], entry['target']
    elif all(isinstance(entry.get(k), str) for k in ('container', 'artifact', 'name')):
        kind, name = entry['artifact'], (entry['container'], entry['name'])
    else:
        return None
    return ('notes',) if kind == 'notes' else (kind, name)


def is_external(entry):
    """A routed_to entry for a delivery other than the vault copy."""
    key = route_key(entry)
    return key is not None and key != ('notes',)


def rewrite(vault, plan):
    """routed_to is unioned, never removed; labels are replaced only when the plan carries them."""
    rewritten, failed = [], []
    for entry in plan.get('notes', []):
        path = vault / 'notes' / f'{entry["slug"]}.md'
        try:
            text, stamp = fm.read(path)
            data = fm.parse(text)
            before = dict(data)
            if entry.get('routed_to'):
                merged = data.get('routed_to') or []
                if not isinstance(merged, list) or not all(route_key(t) for t in merged):
                    raise fm.NoteError('existing routed_to is malformed')
                merged = list(merged)
                seen = {route_key(t) for t in merged}
                for t in entry['routed_to']:
                    if route_key(t) not in seen:
                        merged.append(t)
                        seen.add(route_key(t))
                data['routed_to'] = merged
            if 'labels' in entry:
                data['labels'] = entry['labels']
            if data != before:
                fm.rewrite(path, text, stamp, data)
                rewritten.append(f'notes/{path.name}')
        except (fm.NoteError, OSError, UnicodeDecodeError) as e:
            failed.append({'slug': entry['slug'], 'reason': str(e)})
    return {'rewritten': rewritten, 'failed': failed}


# Each step appends to `done` as each item lands, so a raise part-way leaves an exact record (F3).
def mark(vault, rels, done):
    for rel in rels:
        p = vault / rel
        text = p.read_text(encoding='utf-8')
        if text.startswith('---\n') and re.search(r'^ingested:\s*true\s*$', text[4:text.find('\n---', 4)], re.M):
            pass
        elif text.startswith('---\n'):
            p.write_text(text.replace('---\n', '---\ningested: true\n', 1), encoding='utf-8')
        else:
            p.write_text('---\ningested: true\n---\n' + text, encoding='utf-8')
        done.append(rel)
    return done


def advance(vault, entries, done):
    if not entries:
        return done
    import yaml
    ip = vault / '_machine' / 'ingest_paths.yml'
    data = yaml.safe_load(ip.read_text(encoding='utf-8')) or {'sources': []}
    paths = []
    for adv in entries:
        for s in data.get('sources') or []:
            if s.get('path') == adv['path']:
                s['last_read'] = adv['last_read']
                paths.append(adv['path'])
    ip.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    done.extend(paths)  # one write: all advanced, or none
    return done


def archive(vault, moves, done):
    for mv in moves:
        src = Path(mv['from']).expanduser()
        dest_dir = vault / '_machine' / 'logs' / 'ingest' / mv['date']
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem, suffix = src.stem, src.suffix
        dest, i = dest_dir / src.name, 2
        while dest.exists():
            dest, i = dest_dir / f'{stem}-{i}{suffix}', i + 1
        shutil.move(str(src), dest)
        done.append(str(dest.relative_to(vault)))
    return done


def finish(vault, plan):
    """Commit points, strictly ordered, then report.json with what dispatch-targets gathered: routed, held, warnings."""
    check_manifest_paths(vault, plan)
    report_path = Path(plan['report_path'])
    if not within(report_path.resolve(), (vault / '_machine' / 'logs' / 'ingest').resolve()):
        raise Abort(f'report_path outside the run logs: {report_path}')
    report = dict(plan.get('report', {}), marked=[], advanced=[], moved=[])
    # F3: report.json is written even when a step raises, recording exactly what landed and no `completed`, so the
    # run fails loud and the next run's commit-run --recover (which keys on a dirty report.json) commits it.
    try:
        mark(vault, plan.get('mark_ingested', []), report['marked'])
        advance(vault, plan.get('advance', []), report['advanced'])
        archive(vault, plan.get('archive_moves', []), report['moved'])
    finally:
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
