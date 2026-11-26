"""label-bank merge, show and --dry-run, and relabel-notes --dry-run: the surgeon's script surface.

Run from anywhere:
  python3 -m unittest discover plugins/vault/scripts/tests
"""
import json
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_labels import EXTRA, ROUTING, SEED, Base  # noqa: E402

SOURCES = {'sources': [
    {'path': '/somewhere', 'track': 'vcs', 'lens': ['roadmap', 'idea']},
    {'path': '/elsewhere', 'track': 'destructive', 'lens': ['observation']},
]}


class Surgery(Base):
    def setUp(self):
        super().setUp()
        self.routing_path = self.vault / '_machine' / 'routing.yml'
        self.sources_path = self.vault / '_machine' / 'ingest_paths.yml'
        self.routing_path.write_text('# routing header\n' + yaml.safe_dump(ROUTING, sort_keys=False))
        self.sources_path.write_text(yaml.safe_dump(SOURCES, sort_keys=False))
        self.note('a', ['roadmap', 'todo'], body='Body mentions roadmap.\r\n\r\nCRLF and trailing space \n')
        self.note('b', ['idea', 'roadmap'], extra='source: journal/2026-01-02\n')
        self.note('c', ['idea'])

    def routing(self):
        return yaml.safe_load(self.routing_path.read_text())['rules']

    def lenses(self):
        return [s['lens'] for s in yaml.safe_load(self.sources_path.read_text())['sources']]

    def body(self, slug):
        return (self.vault / 'notes' / f'{slug}.md').read_bytes().split(b'\n---\n', 1)[1]


class Merge(Surgery):
    def test_merge_is_one_atomic_commit_over_bank_notes_rules_and_lenses(self):
        self.init()
        n = self.commits()
        bodies = {s: self.body(s) for s in 'abc'}
        r = self.bank('merge', '--from', 'roadmap', '--into', 'idea')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out['status'], out['from'], out['into'], out['notes']), ('committed', 'roadmap', 'idea', ['a', 'b']))
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.last_files(), ['_machine/ingest_paths.yml', '_machine/labels.yml', '_machine/routing.yml',
                                             'notes/a.md', 'notes/b.md'])
        self.assertIn('label-bank(merge): roadmap -> idea — 2 notes, 2 reference files', self.last_description())
        labels = self.labels()
        self.assertNotIn('roadmap', labels)  # absorbed label removed, not retired
        self.assertEqual(labels['idea'], yaml.safe_load(SEED.read_text())['labels']['idea'])
        self.assertEqual(self.note_labels('a'), ['idea', 'todo'])
        self.assertEqual(self.note_labels('b'), ['idea'])  # already had idea: no duplicate
        self.assertEqual(self.note_labels('c'), ['idea'])
        self.assertEqual({s: self.body(s) for s in 'abc'}, bodies)
        rules = self.routing()
        self.assertEqual(rules[1]['match'], [{'any': ['todo', 'idea']}, {'none': ['project:*', 'idea']}])
        self.assertEqual(rules[1]['to'], ['roadmap'])  # target names are not labels
        self.assertEqual(rules[2]['match'], ['idea', 'project:*'])
        self.assertTrue(self.routing_path.read_text().startswith('# routing header\n'))
        self.assertEqual(self.lenses(), [['idea'], ['observation']])  # deduplicated
        self.assertEqual(self.jj('diff', '--name-only', '-r', '@'), '')

    def test_merge_deduplicates_inside_rule_matches(self):
        self.init()
        r = self.bank('merge', '--from', 'roadmap', '--into', 'todo')  # a protected target is fine
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.routing()[1]['match'], [{'any': ['todo']}, {'none': ['project:*', 'todo']}])
        self.assertEqual(self.note_labels('a'), ['todo'])
        self.assertEqual(self.lenses(), [['todo', 'idea'], ['observation']])

    def test_a_retired_label_merges_into_an_active_one(self):
        self.note('d', ['old-thing', 'observation'])
        self.init()
        r = self.bank('merge', '--from', 'old-thing', '--into', 'observation')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('old-thing', self.labels())
        self.assertEqual(self.note_labels('d'), ['observation'])
        self.assertEqual(self.last_files(), ['_machine/labels.yml', 'notes/d.md'])

    def test_absent_reference_files_are_nothing_to_rewrite(self):
        self.routing_path.unlink()
        self.sources_path.unlink()
        self.init()
        r = self.bank('merge', '--from', 'roadmap', '--into', 'idea')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['references'], [])
        self.assertEqual(self.last_files(), ['_machine/labels.yml', 'notes/a.md', 'notes/b.md'])

    def test_refusals_change_nothing(self):
        self.init()
        before = self.state()
        for args, needle in (
                (('roadmap', 'roadmap'), 'into itself'),
                (('nope', 'idea'), 'no label named nope'),
                (('roadmap', 'nope'), 'no label named nope'),
                (('todo', 'idea'), 'protected'),
                (('workspace:learning', 'idea'), 'imported'),
                (('roadmap', 'workspace:learning'), 'imported'),
                (('roadmap', 'old-thing'), 'retired'),
        ):
            for dry in ((), ('--dry-run',)):
                with self.subTest(args=args, dry=dry):
                    r = self.bank('merge', '--from', args[0], '--into', args[1], *dry)
                    self.assert_refused(r, needle, *before)

    def test_an_uncommitted_file_refuses_the_whole_merge_and_its_dry_run(self):
        for path in (self.vault / 'notes' / 'b.md', self.routing_path, self.bank_path):
            with self.subTest(path=path.name):
                self.init()
                path.write_text(path.read_text() + '# edit\n')
                before = self.state()
                for dry in ((), ('--dry-run',)):
                    r = self.bank('merge', '--from', 'roadmap', '--into', 'idea', *dry)
                    self.assert_refused(r, path.name, *before)
                path.write_text(path.read_text()[:-len('# edit\n')])

    def test_dry_run_reports_and_writes_nothing(self):
        self.init()
        before = self.state()
        r = self.bank('merge', '--from', 'roadmap', '--into', 'idea', '--dry-run')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state(), before)
        out = json.loads(r.stdout)
        self.assertEqual(out['status'], 'planned')
        self.assertEqual(out['notes'], ['a', 'b'])
        self.assertEqual(out['files'], ['_machine/labels.yml', 'notes/a.md', 'notes/b.md', '_machine/routing.yml',
                                        '_machine/ingest_paths.yml'])
        self.assertEqual(out['references'], ['_machine/routing.yml', '_machine/ingest_paths.yml'])
        self.assertEqual(out['reference_edits'], [
            {'file': '_machine/routing.yml', 'index': 1, 'field': 'match',
             'before': [{'any': ['todo', 'roadmap']}, {'none': ['project:*', 'roadmap']}],
             'after': [{'any': ['todo', 'idea']}, {'none': ['project:*', 'idea']}]},
            {'file': '_machine/routing.yml', 'index': 2, 'field': 'match',
             'before': ['roadmap', 'project:*'], 'after': ['idea', 'project:*']},
            {'file': '_machine/ingest_paths.yml', 'index': 0, 'field': 'lens', 'path': '/somewhere',
             'before': ['roadmap', 'idea'], 'after': ['idea']},
        ])


class DryRun(Surgery):
    def test_rename_dry_run_matches_the_real_run(self):
        self.init()
        before = self.state()
        plan = json.loads(self.bank('rename', '--from', 'roadmap', '--to', 'plans', '--dry-run').stdout)
        self.assertEqual(self.state(), before)
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual(len(plan['reference_edits']), 3)
        real = json.loads(self.bank('rename', '--from', 'roadmap', '--to', 'plans').stdout)
        self.assertEqual(sorted(plan['files']), sorted(real['files']))
        self.assertEqual((plan['notes'], plan['references']), (real['notes'], real['references']))

    def test_rename_dry_run_keeps_the_refusals(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('rename', '--from', 'roadmap', '--to', 'idea', '--dry-run'), 'already exists', *before)
        self.assert_refused(self.bank('rename', '--from', 'todo', '--to', 'task', '--dry-run'), 'protected', *before)

    def test_retire_and_update_dry_runs_list_carriers_and_references(self):
        self.init()
        before = self.state()
        for args in (('retire', '--name', 'roadmap'), ('update', '--name', 'roadmap', '--when-to-apply', 'New text.')):
            with self.subTest(op=args[0]):
                r = self.bank(*args, '--dry-run')
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual((out['status'], out['op'], out['files']), ('planned', args[0], ['_machine/labels.yml']))
                self.assertEqual(out['notes'], ['a', 'b'])
                self.assertEqual(out['references'], ['_machine/routing.yml', '_machine/ingest_paths.yml'])
                self.assertEqual(out['reference_edits'], [])
        self.assertEqual(self.state(), before)
        self.assert_refused(self.bank('retire', '--name', 'todo', '--dry-run'), 'protected', *before)
        self.assert_refused(self.bank('update', '--name', 'workspace:learning', '--when-to-apply', 'x', '--dry-run'),
                            'imported', *before)

    def test_a_real_run_omits_the_dry_run_context(self):
        self.init()
        out = json.loads(self.bank('retire', '--name', 'roadmap').stdout)
        self.assertEqual(set(out), {'status', 'op', 'files', 'name'})

    def test_remove_and_add_dry_runs(self):
        self.init()
        before = self.state()
        self.assert_refused(self.bank('remove', '--name', 'roadmap', '--dry-run'), 'still carry roadmap', *before)
        out = json.loads(self.bank('remove', '--name', 'old-thing', '--dry-run').stdout)
        self.assertEqual((out['status'], out['files']), ('planned', ['_machine/labels.yml']))
        out = json.loads(self.bank('add', '--name', 'plans', '--when-to-apply', 'x', '--dry-run').stdout)
        self.assertEqual(out['status'], 'planned')
        self.assertEqual(self.state(), before)
        self.assertNotIn('plans', self.labels())

    def test_an_unchanged_mutation_stays_unchanged(self):
        self.init()
        out = json.loads(self.bank('retire', '--name', 'old-thing', '--dry-run').stdout)
        self.assertEqual(out, {'status': 'unchanged'})


class Show(Surgery):
    def test_show_is_read_only(self):
        self.init()
        before = self.state()
        r = self.bank('show', '--name', 'roadmap')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {
            'name': 'roadmap', 'entry': EXTRA['roadmap'], 'notes': ['a', 'b'],
            'references': ['_machine/routing.yml', '_machine/ingest_paths.yml']})
        out = json.loads(self.bank('show', '--name', 'workspace:learning').stdout)
        self.assertEqual(out['entry']['origin'], 'imported')
        self.assert_refused(self.bank('show', '--name', 'nope'), 'no label named', *before)
        self.assertEqual(self.state(), before)

    def test_show_takes_no_dry_run(self):
        self.init()
        r = self.bank('show', '--name', 'roadmap', '--dry-run')
        self.assertNotEqual(r.returncode, 0)


class RelabelDryRun(Surgery):
    def relabel_dry(self, notes, reason='split roadmap'):
        m = self.tmp / 'manifest.json'
        m.write_text(json.dumps({'reason': reason, 'notes': notes}))
        return self.run_script('relabel-notes', self.vault, m, '--dry-run')

    def test_plans_before_and_after_and_writes_nothing(self):
        self.init()
        before = self.state()
        r = self.relabel_dry({'a': {'add': ['observation'], 'remove': ['roadmap']}, 'c': {'add': ['idea']}})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'status': 'planned', 'notes': {
            'a': {'before': ['roadmap', 'todo'], 'after': ['todo', 'observation']}}})
        self.assertEqual(self.state(), before)

    def test_keeps_the_refusals(self):
        self.init()
        before = self.state()
        self.assert_refused(self.relabel_dry({'a': {'add': ['old-thing']}}), 'not active', *before)
        self.assert_refused(self.relabel_dry({'missing': {'add': ['idea']}}), 'no note named', *before)
        p = self.vault / 'notes' / 'a.md'
        p.write_text(p.read_text() + 'uncommitted\n')
        before = self.state()
        self.assert_refused(self.relabel_dry({'a': {'add': ['observation']}}), 'uncommitted', *before)


if __name__ == '__main__':
    unittest.main()
