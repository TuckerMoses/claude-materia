"""label-bank, relabel-notes and the label bank schema, as tests. Real scripts against a throwaway jj vault.

Run from anywhere:
  python3 -m unittest discover plugins/vault/scripts/tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema
import yaml

SCRIPTS = Path(__file__).resolve().parent.parent
PLUGIN = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import _label_bank as lb  # noqa: E402
import _vault_tx as tx  # noqa: E402

SCHEMA = json.loads((SCRIPTS / 'labels.schema.json').read_text())
SEED = PLUGIN / 'skills' / 'vault' / 'assets' / 'labels.yml'

EXTRA = {
    'roadmap': {'when_to_apply': 'Plans and sequencing of future work.', 'status': 'active'},
    'old-thing': {'when_to_apply': 'Retired long ago.', 'status': 'retired'},
    'workspace:learning': {'when_to_apply': 'The learning workspace.', 'status': 'active', 'origin': 'imported'},
}
ROUTING = {'rules': [
    {'match': ['*'], 'to': ['notes']},
    {'match': [{'any': ['todo', 'roadmap']}, {'none': ['project:*', 'roadmap']}], 'to': ['roadmap']},
    {'match': ['roadmap', 'project:*'], 'to': ['notes']},
]}


def note_text(labels, body='A verbatim body.\n\nWith two paragraphs: roadmap stays here.\n', extra=''):
    return f'---\ntitle: "T"\nlabels: {json.dumps(labels)}\ncreated: 2026-01-02\n{extra}---\n\n{body}'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = self.tmp / 'vault'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'journal').mkdir()
        (self.vault / '_machine').mkdir()
        seed = SEED.read_text()
        bank = yaml.safe_load(seed)
        bank['labels'].update(EXTRA)
        self.bank_path = self.vault / '_machine' / 'labels.yml'
        self.bank_path.write_text('# my header\n\n' + yaml.safe_dump(bank, sort_keys=False))
        subprocess.run(['jj', 'git', 'init', str(self.vault)], capture_output=True, check=True)
        for key, value in (('user.name', 'test'), ('user.email', 'test@test.invalid')):
            subprocess.run(['jj', 'config', 'set', '--repo', key, value], cwd=self.vault, capture_output=True, check=True)

    def init(self):
        """Commit everything written so far as the vault's starting state."""
        subprocess.run(['jj', 'commit', '-m', 'init'], cwd=self.vault, capture_output=True, check=True)

    def note(self, slug, labels, **kw):
        p = self.vault / 'notes' / f'{slug}.md'
        p.write_bytes(note_text(labels, **kw).encode())
        return p

    def run_script(self, *args):
        return subprocess.run([str(SCRIPTS / args[0]), *map(str, args[1:])], capture_output=True, text=True)

    def bank(self, *args):
        return self.run_script('label-bank', args[0], self.vault, *args[1:])

    def relabel(self, notes, reason='tidy labels'):
        m = self.tmp / 'manifest.json'
        m.write_text(json.dumps({'reason': reason, 'notes': notes}))
        return self.run_script('relabel-notes', self.vault, m)

    def jj(self, *args):
        return subprocess.run(['jj', '--no-pager', *args], cwd=self.vault, capture_output=True, text=True,
                              check=True).stdout

    def commits(self):
        return len(self.jj('log', '--no-graph', '-r', '::@-', '-T', 'commit_id ++ "\\n"').split())

    def last_files(self):
        return sorted(self.jj('diff', '--name-only', '-r', '@-').split())

    def last_description(self):
        return self.jj('log', '--no-graph', '-r', '@-', '-T', 'description')

    def labels(self):
        return yaml.safe_load(self.bank_path.read_text())['labels']

    def note_labels(self, slug):
        text = (self.vault / 'notes' / f'{slug}.md').read_text()
        return yaml.safe_load(text[4:text.find('\n---\n', 4)])['labels']

    def snapshot(self):
        return {str(p.relative_to(self.vault)): p.read_bytes() for p in sorted(self.vault.rglob('*'))
                if p.is_file() and '.jj' not in p.parts and '.git' not in p.parts}

    def assert_refused(self, r, needle, before, commits):
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn(needle, r.stderr)
        self.assertEqual(self.snapshot(), before, 'a refusal changed a file')
        self.assertEqual(self.commits(), commits, 'a refusal made a commit')

    def state(self):
        return self.snapshot(), self.commits()


class Schema(unittest.TestCase):
    def check(self, data):
        return list(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))

    def test_seed_template_validates_and_flags_the_four_protected_labels(self):
        data = yaml.safe_load(SEED.read_text())
        self.assertEqual(self.check(data), [])
        self.assertEqual(sorted(k for k, v in data['labels'].items() if v.get('protected')),
                         ['delegated', 'needs-label', 'session-seed', 'todo'])

    def test_names_follow_the_label_pattern(self):
        for good in ('idea', 'ai/agents', 'workspace:learning', 'project:a_b-c', '3d'):
            self.assertEqual(self.check({'labels': {good: {'when_to_apply': 'x', 'status': 'active'}}}), [], good)
        for bad in ('Idea', 'idea\n', '-idea', 'a:b:c', 'a b', 'workspace:', ':x', 'a:B'):
            self.assertNotEqual(self.check({'labels': {bad: {'when_to_apply': 'x', 'status': 'active'}}}), [], bad)

    def test_entry_shape(self):
        ok = {'when_to_apply': 'x', 'status': 'active'}
        self.assertEqual(self.check({'labels': {'a': dict(ok, protected=True, origin='imported')}}), [])
        for bad in ({'status': 'active'}, {'when_to_apply': 'x'}, dict(ok, status='open'), dict(ok, origin='lib'),
                    dict(ok, kind='subject'), dict(ok, when_to_apply=''), dict(ok, when_to_apply='  ')):
            self.assertNotEqual(self.check({'labels': {'a': bad}}), [], bad)
        self.assertNotEqual(self.check({'labels': {}, 'extra': 1}), [])


class Add(Base):
    def test_add_is_one_path_scoped_commit(self):
        self.init()
        (self.vault / 'journal' / '2026-01-05.md').write_text('open day\n')
        n = self.commits()
        r = self.bank('add', '--name', 'ai/agents', '--when-to-apply', 'Agent systems.')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'committed')
        self.assertEqual(self.labels()['ai/agents'], {'when_to_apply': 'Agent systems.', 'status': 'active'})
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.last_files(), ['_machine/labels.yml'])
        self.assertEqual(self.last_description().splitlines()[0], 'label-bank(add): ai/agents')
        self.assertIn('journal/2026-01-05.md', self.jj('diff', '--name-only', '-r', '@'))

    def test_write_keeps_header_order_and_seed_style(self):
        self.init()
        self.bank('add', '--name', 'zz', '--when-to-apply', 'last')
        text = self.bank_path.read_text()
        self.assertTrue(text.startswith('# my header\n\nlabels:\n'))
        names = list(self.labels())
        self.assertEqual(names[:4], ['todo', 'session-seed', 'delegated', 'needs-label'])
        self.assertEqual(names[-1], 'zz')
        self.assertIn('when_to_apply: >-\n', text)
        self.assertIn('workspace:learning:\n', text)

    def test_refusals(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('add', '--name', 'roadmap', '--when-to-apply', 'x'), 'already exists', *before)
        self.assert_refused(self.bank('add', '--name', 'old-thing', '--when-to-apply', 'x'), 'already exists', *before)
        self.assert_refused(self.bank('add', '--name', 'Bad Name', '--when-to-apply', 'x'), 'schema', *before)
        self.assert_refused(self.bank('add', '--name', 'ok', '--when-to-apply', ''), 'schema', *before)

    def test_refuses_when_the_bank_has_uncommitted_changes(self):
        self.init()
        self.bank_path.write_text(self.bank_path.read_text() + '\n')
        before = self.state()
        self.assert_refused(self.bank('add', '--name', 'new', '--when-to-apply', 'x'), 'uncommitted', *before)

    def test_refuses_an_invalid_bank_and_a_non_jj_vault(self):
        self.bank_path.write_text('labels:\n  idea:\n    status: active\n')
        self.init()
        before = self.state()
        self.assert_refused(self.bank('add', '--name', 'new', '--when-to-apply', 'x'), 'schema', *before)
        shutil.rmtree(self.vault / '.jj')
        r = self.bank('add', '--name', 'new', '--when-to-apply', 'x')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('not a jj vault', r.stderr)


class UpdateRetire(Base):
    def test_update_rewrites_text_protected_allowed(self):
        self.init()
        r = self.bank('update', '--name', 'needs-label', '--when-to-apply', 'Waiting on vocabulary.')
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self.labels()['needs-label']
        self.assertEqual(entry, {'when_to_apply': 'Waiting on vocabulary.', 'status': 'active', 'protected': True})
        self.assertEqual(self.last_description().splitlines()[0], 'label-bank(update): needs-label')

    def test_update_refusals_and_noop(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('update', '--name', 'workspace:learning', '--when-to-apply', 'x'), 'imported', *before)
        self.assert_refused(self.bank('update', '--name', 'nope', '--when-to-apply', 'x'), 'no label named', *before)
        r = self.bank('update', '--name', 'roadmap', '--when-to-apply', EXTRA['roadmap']['when_to_apply'])
        self.assertEqual(json.loads(r.stdout), {'status': 'unchanged'})
        self.assertEqual(self.state(), before)

    def test_retire(self):
        self.note('n', ['roadmap'])
        self.init()
        r = self.bank('retire', '--name', 'roadmap')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.labels()['roadmap']['status'], 'retired')
        self.assertEqual(self.note_labels('n'), ['roadmap'])  # notes keep it for history
        self.assertEqual(self.last_files(), ['_machine/labels.yml'])
        before = self.state()
        self.assertEqual(json.loads(self.bank('retire', '--name', 'roadmap').stdout), {'status': 'unchanged'})
        self.assertEqual(self.state(), before)

    def test_retire_refusals(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('retire', '--name', 'todo'), 'protected', *before)
        self.assert_refused(self.bank('retire', '--name', 'workspace:learning'), 'imported', *before)


class Rename(Base):
    def setUp(self):
        super().setUp()
        (self.vault / '_machine' / 'routing.yml').write_text('# routing header\n' + yaml.safe_dump(ROUTING, sort_keys=False))
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': [
            {'path': '/somewhere', 'track': 'vcs', 'lens': ['roadmap', 'idea']},
            {'path': '/elsewhere', 'track': 'destructive', 'lens': ['idea']},
        ]}, sort_keys=False))
        self.body = 'Body mentions roadmap.\r\n\r\nCRLF and trailing space \n'
        self.note('a', ['roadmap', 'todo'], body=self.body)
        self.note('b', ['idea', 'roadmap'], extra='source: journal/2026-01-02\n')
        self.note('c', ['idea'])

    def test_rename_is_one_atomic_commit_over_bank_notes_rules_and_lenses(self):
        self.init()
        n = self.commits()
        body_before = (self.vault / 'notes' / 'a.md').read_bytes().split(b'\n---\n', 1)[1]
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['notes'], ['a', 'b'])
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.last_files(), ['_machine/ingest_paths.yml', '_machine/labels.yml', '_machine/routing.yml',
                                             'notes/a.md', 'notes/b.md'])
        self.assertIn('label-bank(rename): roadmap -> plans', self.last_description())
        labels = self.labels()
        self.assertNotIn('roadmap', labels)  # D11: no old entry left behind
        self.assertEqual(labels['plans'], EXTRA['roadmap'])
        names = list(labels)
        self.assertEqual(names.index('plans'), names.index('old-thing') - 1)  # same place in the bank
        self.assertEqual(self.note_labels('a'), ['plans', 'todo'])  # same place in the note
        self.assertEqual(self.note_labels('b'), ['idea', 'plans'])
        self.assertEqual(self.note_labels('c'), ['idea'])
        self.assertEqual((self.vault / 'notes' / 'a.md').read_bytes().split(b'\n---\n', 1)[1], body_before)
        routing = yaml.safe_load((self.vault / '_machine' / 'routing.yml').read_text())
        self.assertEqual(routing['rules'][1]['match'], [{'any': ['todo', 'plans']}, {'none': ['project:*', 'plans']}])
        self.assertEqual(routing['rules'][1]['to'], ['roadmap'])  # target names are not labels
        self.assertEqual(routing['rules'][2]['match'], ['plans', 'project:*'])
        self.assertTrue((self.vault / '_machine' / 'routing.yml').read_text().startswith('# routing header\n'))
        lenses = [s['lens'] for s in yaml.safe_load((self.vault / '_machine' / 'ingest_paths.yml').read_text())['sources']]
        self.assertEqual(lenses, [['plans', 'idea'], ['idea']])
        self.assertEqual(self.jj('diff', '--name-only', '-r', '@'), '')

    def test_absent_routing_and_sources_are_nothing_to_rewrite(self):
        (self.vault / '_machine' / 'routing.yml').unlink()
        (self.vault / '_machine' / 'ingest_paths.yml').unlink()
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.last_files(), ['_machine/labels.yml', 'notes/a.md', 'notes/b.md'])

    def test_a_retired_label_renames_and_stays_retired(self):
        self.note('d', ['old-thing'])
        self.init()
        r = self.bank('rename', '--from', 'old-thing', '--to', 'older-thing')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.labels()['older-thing']['status'], 'retired')
        self.assertEqual(self.note_labels('d'), ['older-thing'])

    def test_refusals_change_nothing(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'idea'), 'already exists', *before)
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'roadmap'), 'already exists', *before)
        self.assert_refused(self.bank('rename', '--from', 'todo', '--to', 'task'), 'protected', *before)
        self.assert_refused(self.bank('rename', '--from', 'workspace:learning', '--to', 'workspace:study'), 'imported', *before)
        self.assert_refused(self.bank('rename', '--from', 'nope', '--to', 'x'), 'no label named', *before)
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'Plans'), 'schema', *before)

    def test_an_uncommitted_note_refuses_the_whole_rename(self):
        self.init()
        p = self.vault / 'notes' / 'b.md'
        p.write_text(p.read_text() + 'hand edit\n')
        before = self.state()
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'plans'), 'notes/b.md', *before)

    def test_an_uncommitted_routing_file_refuses_the_whole_rename(self):
        self.init()
        p = self.vault / '_machine' / 'routing.yml'
        p.write_text(p.read_text() + '# edit\n')
        before = self.state()
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'plans'), 'routing.yml', *before)

    def test_an_unreadable_note_that_mentions_the_label_refuses(self):
        (self.vault / 'notes' / 'broken.md').write_text('---\nlabels: [roadmap\n---\nbody\n')
        (self.vault / 'notes' / 'broken-other.md').write_text('---\nlabels: [x\n---\nbody\n')
        self.init()
        before = self.state()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assert_refused(r, 'broken', *before)
        self.assertNotIn('broken-other', r.stderr)

    def test_a_failing_routing_file_refuses_the_whole_rename(self):
        (self.vault / '_machine' / 'routing.yml').write_text('rules: [\n')
        self.init()
        before = self.state()
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'plans'), 'routing.yml', *before)


class Remove(Base):
    def test_remove(self):
        self.note('n', ['idea'])
        self.init()
        r = self.bank('remove', '--name', 'roadmap')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('roadmap', self.labels())
        self.assertEqual(self.last_files(), ['_machine/labels.yml'])

    def test_refusals(self):
        self.note('n', ['old-thing'])
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': [{'path': '/x', 'lens': ['roadmap']}]}))
        self.init()
        before = self.state()
        self.assert_refused(self.bank('remove', '--name', 'old-thing'), 'still carry old-thing', *before)
        self.assert_refused(self.bank('remove', '--name', 'roadmap'), 'ingest_paths.yml', *before)
        self.assert_refused(self.bank('remove', '--name', 'needs-label'), 'protected', *before)
        self.assert_refused(self.bank('remove', '--name', 'workspace:learning'), 'imported', *before)
        self.assert_refused(self.bank('remove', '--name', 'nope'), 'no label named', *before)


class Relabel(Base):
    def setUp(self):
        super().setUp()
        self.body = 'Line one.\r\nLine two with labels: [todo]\n\n\n'
        self.note('a', ['idea', 'needs-label'], body=self.body)
        self.note('b', ['idea'])
        self.note('c', ['observation'])

    def test_adds_and_removes_in_one_commit_bodies_untouched(self):
        self.init()
        n = self.commits()
        raw = (self.vault / 'notes' / 'a.md').read_bytes()
        r = self.relabel({'a': {'add': ['roadmap', 'idea'], 'remove': ['needs-label', 'never-existed']},
                          'b': {'add': ['workspace:learning']}}, reason='accept roadmap\n\nfrom the resolve sitting')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'status': 'committed', 'notes': ['a', 'b']})
        self.assertEqual(self.note_labels('a'), ['idea', 'roadmap'])
        self.assertEqual(self.note_labels('b'), ['idea', 'workspace:learning'])
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.last_files(), ['notes/a.md', 'notes/b.md'])
        desc = self.last_description()
        self.assertTrue(desc.startswith('relabel: accept roadmap\n\nfrom the resolve sitting\n'))
        self.assertIn('- a: +roadmap +idea -needs-label -never-existed', desc)
        new = (self.vault / 'notes' / 'a.md').read_bytes()
        self.assertEqual(new.split(b'\n---\n', 1)[1], raw.split(b'\n---\n', 1)[1])
        self.assertIn(b'created: 2026-01-02\n', new)  # other fields keep their types

    def test_unchanged_is_no_commit(self):
        self.init()
        before = self.state()
        r = self.relabel({'b': {'add': ['idea'], 'remove': ['todo']}})
        self.assertEqual(json.loads(r.stdout)['status'], 'unchanged')
        self.assertEqual(self.state(), before)

    def test_added_labels_must_be_active(self):
        self.init()
        before = self.state()
        self.assert_refused(self.relabel({'a': {'add': ['old-thing']}}), 'not active in the bank: old-thing', *before)
        self.assert_refused(self.relabel({'a': {'add': ['roadmap']}, 'b': {'add': ['invented']}}), 'invented', *before)

    def test_all_or_nothing(self):
        (self.vault / 'notes' / 'broken.md').write_text('no frontmatter at all\n')
        self.init()
        before = self.state()
        self.assert_refused(self.relabel({'a': {'add': ['roadmap']}, 'missing': {'add': ['roadmap']}}), 'no note named missing', *before)
        self.assert_refused(self.relabel({'a': {'add': ['roadmap']}, 'broken': {'add': ['roadmap']}}), 'broken', *before)
        p = self.vault / 'notes' / 'b.md'
        p.write_text(p.read_text() + 'uncommitted\n')
        before = self.state()
        self.assert_refused(self.relabel({'a': {'add': ['roadmap']}, 'b': {'add': ['roadmap']}}), 'uncommitted', *before)

    def test_manifest_refusals(self):
        self.init()
        before = self.state()
        self.assert_refused(self.relabel({'a': {'add': ['roadmap'], 'remove': ['roadmap']}}), 'both added and removed', *before)
        self.assert_refused(self.relabel({'a': {'add': ['roadmap']}}, reason=' '), 'reason', *before)
        self.assert_refused(self.relabel({}), 'notes', *before)
        self.assert_refused(self.relabel({'a': {'labels': ['roadmap']}}), 'an edit is', *before)
        self.assert_refused(self.relabel({'a': {'add': 'roadmap'}}), 'list of strings', *before)
        self.assert_refused(self.relabel({'../labels': {'add': ['roadmap']}}), 'not a note slug', *before)


class Transaction(Base):
    """The rollback path, in process: a check that fails after every file was written restores them all."""

    def test_a_failed_verification_restores_every_file_and_commits_nothing(self):
        self.note('a', ['idea'])
        self.note('b', ['idea'])
        self.init()
        before = self.state()
        changes = [lb.note_change(self.vault, s, lambda ls: ls + ['roadmap']) for s in ('a', 'b')]

        def tamper(back):
            raise lb.BankError('verification failed')
        changes[1].check = tamper
        with self.assertRaises(tx.TxError) as cm:
            tx.apply(self.vault, changes, 'relabel: x')
        self.assertIn('nothing changed', str(cm.exception))
        self.assertEqual(self.state(), before)

    def test_the_body_check_catches_a_changed_body(self):
        self.note('a', ['idea'])
        change = lb.note_change(self.vault, 'a', lambda ls: ls + ['roadmap'])
        change.check(change.new)
        with self.assertRaises(lb.BankError):
            change.check(change.new.replace('verbatim', 'edited'))

    def test_a_concurrent_edit_aborts(self):
        self.note('a', ['idea'])
        self.init()
        change = lb.note_change(self.vault, 'a', lambda ls: ls + ['roadmap'])
        p = self.vault / 'notes' / 'a.md'
        p.write_text(p.read_text() + 'x')
        os.utime(p, ns=(change.stamp[0] + 10 ** 9, change.stamp[0] + 10 ** 9))
        subprocess.run(['jj', 'commit', '-m', 'someone else'], cwd=self.vault, capture_output=True, check=True)
        edited = p.read_bytes()
        with self.assertRaises(tx.TxError):
            tx.apply(self.vault, [change], 'relabel: x')
        self.assertEqual(p.read_bytes(), edited)


if __name__ == '__main__':
    unittest.main()
