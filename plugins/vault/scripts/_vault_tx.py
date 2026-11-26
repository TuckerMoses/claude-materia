"""One vault transaction: rewrite a set of files and land them as exactly one path-scoped jj commit, or change nothing.

Shared by label-bank and relabel-notes. The commit discipline is commit-run's: every jj call is bounded
($VAULT_INGEST_CALL_TIMEOUT, default 300 s) with no stdin and no pager; the commit names its paths, so unrelated
working-copy changes stay uncommitted; an empty commit is abandoned. A file that already has uncommitted changes is
refused, so a commit never carries someone else's edit. Any failure after the first write restores every file.
"""
import os
import subprocess
from pathlib import Path

TIMEOUT = int(os.environ.get('VAULT_INGEST_CALL_TIMEOUT', '300'))


class TxError(Exception):
    """The transaction did not land. Nothing in the vault changed."""


def jj(vault, *args):
    try:
        return subprocess.run(['jj', '--no-pager', *args], cwd=str(vault), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(['jj', *args], 124, '', f'jj {args[0]} timed out after {TIMEOUT}s')


def require_vault(vault):
    if not (Path(vault) / '.jj').is_dir():
        raise TxError(f'not a jj vault: {vault}')


def read(path):
    """(text, stamp) exactly as stored; the stamp is what a write compares against."""
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    st = Path(path).stat()
    return text, (st.st_mtime_ns, st.st_size)


def dirty(vault):
    r = jj(vault, 'diff', '--name-only', '-r', '@')
    if r.returncode != 0:
        raise TxError(f'jj diff failed: {r.stderr.strip()}')
    return {line for line in r.stdout.splitlines() if line}


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
        r = jj(vault, 'commit', '-m', message, *rels)
        if r.returncode != 0:
            raise TxError(f'jj commit failed: {r.stderr.strip()}')
        e = jj(vault, 'log', '--no-graph', '-r', '@-', '-T', 'if(empty, "EMPTY", "NONEMPTY")')
        if e.stdout.strip() != 'NONEMPTY':
            jj(vault, 'abandon', '@-')
            raise TxError('commit selected no changes (empty commit abandoned)')
    except Exception as exc:
        failures = []
        for c in reversed(written):
            try:
                _replace(vault / c.rel, c.old)
            except Exception as e:  # keep restoring the rest; report what could not be put back
                failures.append(f'{c.rel}: {e}')
        why = str(exc) if isinstance(exc, TxError) else f'{type(exc).__name__}: {exc}'
        if failures:
            raise TxError(f'{why}; RESTORE FAILED for {"; ".join(failures)}')
        raise TxError(f'{why}; nothing changed')
