"""One vault transaction: rewrite a set of files and land them as exactly one path-scoped jj commit, or change nothing.

Shared by label-bank, label-proposals, relabel-notes and commit-run. The commit discipline: every jj call is bounded
($VAULT_INGEST_CALL_TIMEOUT, default 300 s) with no stdin and no pager; the commit names its paths as exact-path
filesets (root-file:"..."), so no file name is read as a fileset expression and unrelated working-copy changes stay
uncommitted; the landed commit's changed paths are compared with the intended set, and a commit that carries anything
else (or nothing) is abandoned. A file that already has uncommitted changes is refused, so a commit never carries
someone else's edit. Any failure after the first write restores every file, unless the file changed again since this
transaction wrote it: that file is left alone and named.
"""
import os
import subprocess
from pathlib import Path

TIMEOUT = int(os.environ.get('VAULT_INGEST_CALL_TIMEOUT', '300'))


class TxError(Exception):
    """The transaction did not land. Nothing in the vault changed, unless the message says otherwise."""


class CommitError(TxError):
    """commit_exact did not land its paths. UNKNOWN: whether the history changed could not be established, so the
    caller must not restore files over what may be a landed commit."""

    def __init__(self, message, unknown=False):
        super().__init__(message)
        self.unknown = unknown


def jj(vault, *args):
    try:
        return subprocess.run(['jj', '--no-pager', *args], cwd=str(vault), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(['jj', *args], 124, '', f'jj {args[0]} timed out after {TIMEOUT}s')


def fileset(rel):
    """REL as a fileset matching exactly that one file: jj otherwise parses ~ & | ( ) and spaces as operators."""
    return 'root-file:"' + rel.replace('\\', '\\\\').replace('"', '\\"') + '"'


def require_vault(vault):
    if not (Path(vault) / '.jj').is_dir():
        raise TxError(f'not a jj vault: {vault}')


def read(path):
    """(text, stamp) exactly as stored; the stamp is what a write compares against."""
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    st = Path(path).stat()
    return text, (st.st_mtime_ns, st.st_size)


def changed(vault, rev):
    """The paths revision REV changes."""
    r = jj(vault, 'diff', '--name-only', '-r', rev)
    if r.returncode != 0:
        raise TxError(f'jj diff failed: {r.stderr.strip()}')
    return {line for line in r.stdout.splitlines() if line}


def dirty(vault):
    return changed(vault, '@')


def _field(vault, rev, template):
    r = jj(vault, 'log', '--no-graph', '-r', rev, '-T', template)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def commit_exact(vault, rels, message):
    """Commit exactly RELS (each with a change in @) as one commit and return its commit id, or raise CommitError.

    Whether the commit landed is read from the history, never from jj's exit status: a timed-out or failed `jj
    commit` may still have written it. A landed commit whose changed paths are not exactly RELS is abandoned with its
    content left in the working copy (--restore-descendants), so the history is as before."""
    want = set(rels)
    if not want:
        raise CommitError('nothing to commit')
    change = _field(vault, '@', 'change_id')
    if change is None:
        raise CommitError('cannot read the working-copy change id; nothing committed')
    r = jj(vault, 'commit', '-m', message, *[fileset(p) for p in sorted(want)])
    why = f' (jj exited {r.returncode}: {r.stderr.strip()})' if r.returncode != 0 else ''
    now = _field(vault, '@', 'change_id')
    if now is None:
        raise CommitError(f'cannot tell whether the commit landed{why}; check `jj log` before retrying', unknown=True)
    if now == change:
        raise CommitError(f'jj commit failed: {r.stderr.strip()}' if r.returncode != 0 else
                          'jj commit exited 0 but no commit landed')
    commit = _field(vault, change, 'commit_id')
    try:
        if commit is None:
            raise TxError('cannot read the new commit')
        got = changed(vault, commit)
    except TxError as e:
        raise CommitError(f'a commit landed{why} but could not be verified ({e}); check `jj log`', unknown=True)
    if got == want:
        return commit
    a = jj(vault, 'abandon', '--restore-descendants', commit)
    extra, missing = sorted(got - want), sorted(want - got)
    what = (f'carried {", ".join(extra)} beyond its paths' if extra else '') + ('; ' if extra and missing else '') + \
        (f'left out {", ".join(missing)}' if missing else '')
    if a.returncode != 0:
        raise CommitError(f'commit {commit[:12]} {what} and could not be abandoned: {a.stderr.strip()}', unknown=True)
    raise CommitError(f'the commit {what}{why}; abandoned, history unchanged')


class Change:
    """Replace REL (vault-relative) from OLD to NEW. CHECK, if given, is called on the text read back after the write
    and raises to abort the whole transaction."""

    def __init__(self, rel, old, stamp, new, check=None):
        self.rel, self.old, self.stamp, self.new, self.check = rel, old, stamp, new, check


def _replace(path, text, stamp=None):
    tmp = path.with_name(f'.{path.name}.tx-tmp')
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        if stamp is not None:
            st = path.stat()
            if (st.st_mtime_ns, st.st_size) != stamp:
                raise TxError(f'{path.name} changed while this script was running')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _restore(path, ours, old):
    """Put OLD back at PATH, but only over OURS: a file someone changed after this transaction wrote it is theirs.
    Content already equal to OLD needs nothing."""
    try:
        current = read(path)[0]
    except FileNotFoundError:
        current = None
    if current == old:
        return
    if current != ours:
        raise TxError('changed by someone else after this transaction wrote it; left as it is, restore it by hand')
    _replace(path, old)


def apply(vault, changes, message):
    """Write every change, verify it, commit them as one. Raises TxError (with the vault restored) on any failure."""
    vault = Path(vault)
    require_vault(vault)
    rels = [c.rel for c in changes]
    if len(set(rels)) != len(rels):
        raise TxError('a path appears twice in one transaction')
    held = sorted(set(rels) & dirty(vault))
    if held:
        raise TxError(f'uncommitted changes in {", ".join(held)}; commit or restore them first')
    written = []
    try:
        for c in changes:
            _replace(vault / c.rel, c.new, c.stamp)
            written.append(c)
        for c in changes:
            back, _ = read(vault / c.rel)
            if back != c.new:
                raise TxError(f'{c.rel} did not read back as written')
            if c.check:
                c.check(back)
        want = set(rels) & dirty(vault)
        if not want:
            raise TxError('commit selected no changes (nothing written differs from the history)')
        commit_exact(vault, want, message)
    except Exception as exc:
        why = str(exc) if isinstance(exc, TxError) else f'{type(exc).__name__}: {exc}'
        if isinstance(exc, CommitError) and exc.unknown:
            raise TxError(f'{why}; files NOT restored: they hold the new content, committed or not')
        failures = []
        for c in reversed(written):
            try:
                _restore(vault / c.rel, c.new, c.old)
            except Exception as e:  # keep restoring the rest; report what could not be put back
                failures.append(f'{c.rel}: {e}')
        if failures:
            raise TxError(f'{why}; RESTORE FAILED for {"; ".join(failures)}')
        raise TxError(f'{why}; nothing changed')
