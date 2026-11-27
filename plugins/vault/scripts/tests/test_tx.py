"""_vault_tx: exact-path commits, landed-commit detection and a restore that never clobbers a concurrent edit.

Run from anywhere:
  python3 -m unittest discover plugins/vault/scripts/tests
"""
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_labels import ROUTING, Base, lb, tx  # noqa: E402

# Each of these is a fileset operator or a parse error when handed to jj as a bare path.
ODD = ['a~b', 'c&d', 'e|f', 'g(h)', 'i j', 'k"l']


class OddNames(Base):
    def setUp(self):
        super().setUp()
        (self.vault / '_machine' / 'routing.yml').write_text(yaml.safe_dump(ROUTING, sort_keys=False))
        for slug in ODD:
            self.note(slug, ['roadmap', 'idea'])
        self.note('plain', ['roadmap'])
        self.init()

    def assert_all_committed(self, r, op):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.jj('diff', '--name-only', '-r', '@'), '', f'{op} left files out of its commit')
        committed = self.last_files()
        for slug in ODD + ['plain']:
            self.assertIn(f'notes/{slug}.md', committed)

    def test_rename(self):
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assert_all_committed(r, 'rename')
        for slug in ODD:
            self.assertEqual(self.note_labels(slug), ['plans', 'idea'])

    def test_merge(self):
        r = self.bank('merge', '--from', 'roadmap', '--into', 'idea')
        self.assert_all_committed(r, 'merge')
        for slug in ODD:
            self.assertEqual(self.note_labels(slug), ['idea'])

    def test_relabel(self):
        r = self.relabel({slug: {'remove': ['roadmap']} for slug in ODD + ['plain']})
        self.assert_all_committed(r, 'relabel')

    def test_fileset_quotes_backslash_and_quote(self):
        self.assertEqual(tx.fileset('a\\b"c.md'), 'root-file:"a\\\\b\\"c.md"')


class Verify(Base):
    def setUp(self):
        super().setUp()
        self.note('a~b', ['idea'])
        self.note('ok', ['idea'])
        self.init()
        self.changes = [lb.note_change(self.vault, s, lambda ls: ls + ['roadmap']) for s in ('a~b', 'ok')]

    def test_a_commit_missing_a_path_is_abandoned_and_every_file_restored(self):
        """The old bare-path bug, forced back in: the landed commit leaves a~b.md out, so it must not count."""
        before = self.state()
        real = tx.fileset
        tx.fileset = lambda rel: rel
        try:
            with self.assertRaises(tx.TxError) as cm:
                tx.apply(self.vault, self.changes, 'relabel: x')
        finally:
            tx.fileset = real
        self.assertIn('left out notes/a~b.md', str(cm.exception))
        self.assertIn('nothing changed', str(cm.exception))
        self.assertEqual(self.state(), before)

    def test_a_timed_out_commit_that_landed_is_reported_as_landed(self):
        real = tx.jj

        def slow(vault, *args):
            r = real(vault, *args)
            if args[0] == 'commit':  # jj wrote the commit, then the call timed out
                return subprocess.CompletedProcess(args, 124, '', 'jj commit timed out after 300s')
            return r
        n = self.commits()
        tx.jj = slow
        try:
            tx.apply(self.vault, self.changes, 'relabel: x')
        finally:
            tx.jj = real
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.last_files(), ['notes/a~b.md', 'notes/ok.md'])
        self.assertEqual(self.note_labels('ok'), ['idea', 'roadmap'])
        self.assertEqual(self.jj('diff', '--name-only', '-r', '@'), '')

    def test_a_timed_out_commit_that_did_not_land_restores(self):
        real = tx.jj
        before = self.state()

        def stuck(vault, *args):
            if args[0] == 'commit':
                return subprocess.CompletedProcess(args, 124, '', 'jj commit timed out after 300s')
            return real(vault, *args)
        tx.jj = stuck
        try:
            with self.assertRaises(tx.TxError) as cm:
                tx.apply(self.vault, self.changes, 'relabel: x')
        finally:
            tx.jj = real
        self.assertIn('nothing changed', str(cm.exception))
        self.assertEqual(self.state(), before)

    def test_unknown_landing_restores_nothing(self):
        real = tx.jj
        calls = []

        def blind(vault, *args):
            r = real(vault, *args)
            if args[0] == 'commit':
                calls.append(1)
            if calls and args[0] == 'log':  # after the commit, the history cannot be read
                return subprocess.CompletedProcess(args, 1, '', 'jj broke')
            return r
        tx.jj = blind
        try:
            with self.assertRaises(tx.TxError) as cm:
                tx.apply(self.vault, self.changes, 'relabel: x')
        finally:
            tx.jj = real
        self.assertIn('cannot tell', str(cm.exception))
        self.assertIn('NOT restored', str(cm.exception))
        self.assertEqual(self.note_labels('ok'), ['idea', 'roadmap'])  # left as written: it may be in the history

    def test_restore_does_not_clobber_a_concurrent_edit(self):
        p = self.vault / 'notes' / 'ok.md'

        def someone_edits(back):
            p.write_text(back + 'their line\n')
            raise lb.BankError('verification failed')
        self.changes[1].check = someone_edits
        with self.assertRaises(tx.TxError) as cm:
            tx.apply(self.vault, self.changes, 'relabel: x')
        msg = str(cm.exception)
        self.assertIn('RESTORE FAILED for notes/ok.md', msg)
        self.assertIn('changed by someone else', msg)
        self.assertTrue(p.read_text().endswith('their line\n'))
        self.assertEqual(self.note_labels('a~b'), ['idea'])  # the untouched file is still restored


if __name__ == '__main__':
    unittest.main()
