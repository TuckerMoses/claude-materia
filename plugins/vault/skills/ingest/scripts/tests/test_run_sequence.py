"""The Ingest run sequence's invariants as tests. Real scripts, a throwaway jj vault, a throwaway lib with day-one data.

Needs AGENT_LIB pointing at a real lib (its code is copied, its data is not). Run from anywhere:
  python3 -m unittest discover plugins/vault/skills/ingest/scripts/tests
"""
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import _ingest_keys  # noqa: E402

TODAY = datetime.date.today().isoformat()
D1, D2 = '2026-01-02', '2026-01-03'
ACTION = {'any': ['todo', 'session-seed', 'delegated']}
RULES = {'rules': [
    {'match': ['*'], 'to': [{'container': 'vault', 'artifact': 'notes'}]},
    {'match': [ACTION, 'project:*'], 'to': [{'container': 'project', 'artifact': 'backlog'}]},
    {'match': [ACTION, 'workspace:*', {'none': ['project:*']}], 'to': [{'container': 'workspace', 'artifact': 'backlog'}]},
    {'match': [ACTION, {'none': ['project:*', 'workspace:*']}], 'to': [{'container': 'kernel', 'artifact': 'backlog'}]},
]}


def note(body, labels=('idea',), day=D1, title=None, **extra):
    return dict({'title': title or body[:40], 'labels': list(labels), 'created': TODAY, 'captured': day,
                 'source': f'journal/{day}', 'body': body}, **extra)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = self.tmp / 'vault'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'journal').mkdir()
        (self.vault / '_machine' / 'logs' / 'ingest').mkdir(parents=True)
        (self.vault / '_machine' / 'ingest_paths.yml').write_text('sources: []\n')
        subprocess.run(['jj', 'git', 'init', str(self.vault)], capture_output=True, check=True)
        self.lib = self.tmp / 'lib'
        shutil.copytree(os.environ['AGENT_LIB'], self.lib, ignore=shutil.ignore_patterns(
            '.jj', '__pycache__', 'labels.yml', 'routing.yml', 'containers.yml', 'tests', '.lock'))
        self.rows = [{'name': 'vault', 'kind': 'vault', 'path': str(self.vault), 'artifacts': {'notes': 'notes/'}}]
        for kind, name in (('kernel', 'kernel'), ('workspace', 'values'), ('workspace', 'gaming')):
            d = self.tmp / name
            d.mkdir()
            (d / 'BACKLOG.yml').write_text('items: []\n')
            self.rows.append({'name': name, 'kind': kind, 'path': str(d), 'artifacts': {'backlog': 'BACKLOG.yml'}})
        self.save_lib()
        self.run_id = '2026-11-02-1'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()

    def save_lib(self, rules=RULES):
        (self.lib / 'data' / 'containers.yml').write_text(yaml.safe_dump({'containers': self.rows}))
        (self.lib / 'data' / 'routing.yml').write_text(yaml.safe_dump(rules))

    def env(self):
        return dict(os.environ, AGENT_LIB=str(self.lib))

    def script(self, name, *args):
        return subprocess.run([str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True, env=self.env())

    def day(self, date, text='some day text\n'):
        p = self.vault / 'journal' / f'{date}.md'
        p.write_text(text)
        return p

    def manifest(self, notes, marks=None, name='proposals.json', **extra):
        path = self.run_dir / name
        path.write_text(json.dumps(dict({'notes': notes, 'mark_ingested': marks if marks is not None else [], 'advance': [], 'archive_moves': []}, **extra)))
        return path

    def dispatch(self, notes, marks=None, mode='silent', **extra):
        name = 'confirmed-manifest.json' if mode == 'interactive' else 'proposals.json'
        r = self.script('dispatch-targets', 'run', self.vault, self.manifest(notes, marks, name=name, **extra), '--mode', mode)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def items(self, name='values'):
        return yaml.safe_load((self.tmp / name / 'BACKLOG.yml').read_text())['items']

    def fm(self, slug):
        text = (self.vault / 'notes' / f'{slug}.md').read_text()
        return yaml.safe_load(text[4:text.find('\n---\n', 4)])

    def body(self, slug):
        text = (self.vault / 'notes' / f'{slug}.md').read_text()
        return text[text.find('\n---\n', 4) + 5:]

    def commit(self, report_name='report.json', mode='silent'):
        report = json.loads((self.run_dir / report_name).read_text())
        (self.run_dir / 'run.json').write_text(json.dumps({'filed': len(report['written']), 'day_files': 1, 'parked': 0, 'marked': report['marked'], 'ts': 1}))
        (self.run_dir / 'entry.md').write_text('## run\n')
        if not (self.run_dir / 'proposals.json').exists():
            (self.run_dir / 'proposals.json').write_text('{}')
        return self.script('commit-run', self.vault, self.run_dir / 'report.json', self.run_dir / 'entry.md', self.run_id, mode)

    def marked(self, date):
        return (self.vault / 'journal' / f'{date}.md').read_text().startswith('---\ningested: true')


class Keys(unittest.TestCase):
    def test_trailing_newlines_do_not_change_the_key(self):
        self.assertEqual(_ingest_keys.thought_ref('s', 'body'), _ingest_keys.thought_ref('s', 'body\n\n'))
        self.assertEqual(_ingest_keys.body_md5('body\n'), _ingest_keys.body_md5('body'))
        self.assertNotEqual(_ingest_keys.body_md5('body '), _ingest_keys.body_md5('body'))
        self.assertTrue(_ingest_keys.thought_ref('journal/x', 'b').startswith('journal/x+'))

    def test_day_md5_is_of_the_bytes(self):
        with tempfile.NamedTemporaryFile('wb') as f:
            f.write(b'\xff\n')
            f.flush()
            
            import hashlib
            self.assertEqual(_ingest_keys.day_md5(f.name), hashlib.md5(b'\xff\n').hexdigest())


class FileNotes(Base):
    def test_long_title_never_leaves_a_trailing_hyphen(self):
        self.day(D1)
        self.dispatch([note('b', title='a' * 79 + ' tail')], [f'journal/{D1}.md'])
        self.assertTrue((self.vault / 'notes' / f'{"a" * 79}.md').exists())

    def test_title_with_quote_and_colon_emits_parseable_frontmatter_with_real_dates(self):
        self.day(D1)
        self.dispatch([note('b', title='He said: "go"')], [f'journal/{D1}.md'])
        data = self.fm('he-said-go')
        self.assertEqual(data['title'], 'He said: "go"')
        self.assertIsInstance(data['created'], datetime.date)
        self.assertIsInstance(data['captured'], datetime.date)

    def test_emitted_labels_stay_a_flow_list_and_keep_key_order(self):
        self.day(D1)
        self.dispatch([note('b', title='t', labels=['idea', 'workspace:values'], related=['[[x]]'])], [f'journal/{D1}.md'])
        text = (self.vault / 'notes' / 't.md').read_text()
        self.assertIn('labels: [idea, ', text)
        self.assertEqual(list(self.fm('t'))[:5], ['title', 'labels', 'created', 'captured', 'source'])

    def test_body_is_verbatim(self):
        self.day(D1)
        body = 'line one\n\n  indented: "q" — dash\n---\nafter a rule\n'
        self.dispatch([note(body, title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.body('t').lstrip('\n'), body)

    def confined(self, label, manifest):
        before = sorted(p.name for p in (self.vault / 'notes').iterdir())
        path = self.manifest(**manifest)
        r = self.script('dispatch-targets', 'run', self.vault, path, '--mode', 'silent')
        self.assertNotEqual(r.returncode, 0, label)
        self.assertEqual(sorted(p.name for p in (self.vault / 'notes').iterdir()), before, label)

    def test_manifest_paths_are_confined_before_anything_is_written(self):
        outside = self.tmp / 'outside'
        outside.mkdir()
        target = outside / 'target.txt'
        target.write_text('keep\n')
        n = [note('x', title='should-not-file')]
        self.confined('absolute mark', {'notes': n, 'marks': [str(target)]})
        self.assertEqual(target.read_text(), 'keep\n')
        self.confined('traversal mark', {'notes': n, 'marks': ['journal/../CLAUDE.md']})
        self.confined('date traversal', {'notes': n, 'archive_moves': [{'from': str(target), 'date': '../../../../../outside'}]})
        self.confined('unregistered source', {'notes': n, 'archive_moves': [{'from': str(target), 'date': '2026-07-05'}]})
        self.assertEqual(target.read_text(), 'keep\n')

    def test_registered_destructive_source_still_archives(self):
        src = self.tmp / 'staging'
        src.mkdir()
        (src / 'a.md').write_text('content\n')
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump(
            {'sources': [{'path': str(src), 'track': 'destructive', 'lens': ['idea']}]}))
        report = self.script('dispatch-targets', 'run', self.vault, self.manifest([], archive_moves=[{'from': str(src / 'a.md'), 'date': '2026-07-05'}]), '--mode', 'silent', '--no-journal')
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)['moved'], ['_machine/logs/ingest/2026-07-05/a.md'])

    def test_empty_body_aborts_before_any_write_or_marker(self):
        self.day(D1)
        path = self.manifest([note('fine', title='fine'), note('  ', title='empty')], [f'journal/{D1}.md'])
        r = self.script('dispatch-targets', 'run', self.vault, path, '--mode', 'silent')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('iron rule', r.stderr)
        self.assertFalse((self.vault / 'notes' / 'fine.md').exists())
        self.assertFalse(self.marked(D1))


class Routing(Base):
    def test_multicast_to_vault_and_backlog_with_the_note_slug_as_id(self):
        self.day(D1)
        report = self.dispatch([note('Do the thing', ['todo', 'workspace:values'], title='Do the thing')], [f'journal/{D1}.md'])
        item = self.items()[0]
        self.assertEqual(item['id'], 'do-the-thing')
        self.assertEqual(item['source'], f'journal/{D1}')
        self.assertEqual(item['added'].isoformat(), D1)
        self.assertEqual(item['body'], 'Do the thing')
        self.assertEqual(item['labels'], ['todo', 'workspace:values'])
        self.assertEqual(report['written'], ['notes/do-the-thing.md'])

    def test_vault_copy_records_only_successful_targets_without_a_path(self):
        self.day(D1)
        self.dispatch([note('x', ['todo', 'workspace:values'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.fm('t')['routed_to'], [
            {'container': 'vault', 'artifact': 'notes', 'name': 'vault'},
            {'container': 'workspace', 'artifact': 'backlog', 'name': 'values'}])

    def test_report_audit_shape(self):
        self.day(D1)
        report = self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(report['routed'], [{'id': 't', 'targets': [
            {'container': 'vault', 'artifact': 'notes', 'name': 'vault'},
            {'container': 'kernel', 'artifact': 'backlog', 'name': 'kernel'}],
            'labels': ['todo'], 'source': f'journal/{D1}', 'body_md5': _ingest_keys.body_md5('x')}])
        self.assertEqual(json.loads((self.run_dir / 'report.json').read_text())['routed'], report['routed'])

    def test_tie_warning_reaches_the_report_and_the_status(self):
        self.day(D1)
        report = self.dispatch([note('x', ['todo', 'workspace:values', 'workspace:gaming'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.items('gaming')[0]['id'], 't')
        self.assertEqual(self.items('values'), [])
        self.assertEqual(report['warnings'][0]['message'], 'tie resolved: chose workspace:gaming over workspace:values for kind workspace')
        self.assertEqual(report['held'], [])
        self.assertTrue(self.marked(D1))
        status = self.script('ingest-status', self.vault).stdout
        self.assertIn('routing warnings', status)
        self.assertIn('tie resolved', status)

    def test_a_typo_label_beside_a_real_one_is_visible(self):
        self.day(D1)
        report = self.dispatch([note('x', ['todo', 'workspace:valuez', 'workspace:values'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.items()[0]['id'], 't')
        self.assertIn('workspace:valuez has no registered row', report['warnings'][0]['message'])

    def test_unknown_artifact_fails_before_anything_is_written(self):
        self.day(D1)
        rules = {'rules': RULES['rules'] + [{'match': ['*'], 'to': [{'container': 'vault', 'artifact': 'mystery'}]}]}
        self.rows[0]['artifacts']['mystery'] = 'notes/'
        self.save_lib(rules)
        r = self.script('dispatch-targets', 'run', self.vault, self.manifest([note('x', title='t')], [f'journal/{D1}.md']), '--mode', 'silent')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('mystery', r.stderr)
        self.assertFalse((self.vault / 'notes' / 't.md').exists())
        self.assertFalse(self.marked(D1))

    def test_gate_route_shows_destinations_and_writes_nothing(self):
        path = self.manifest([note('x', ['todo', 'workspace:values'], title='t')])
        r = self.script('dispatch-targets', 'route', self.vault, path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(t['name'] for t in json.loads(r.stdout)[0]['targets']), ['values', 'vault'])
        self.assertEqual(list((self.vault / 'notes').iterdir()), [])
        self.assertEqual(self.items(), [])

    def test_table_order_supplier_first_even_if_rules_list_the_backlog_first(self):
        self.day(D1)
        rules = {'rules': [RULES['rules'][3], RULES['rules'][0]]}
        self.save_lib(rules)
        self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.items('kernel')[0]['id'], 't')

    def test_no_sink_or_label_is_named_in_the_dispatcher_code(self):
        text = (SCRIPTS / 'dispatch-targets').read_text()
        code = text[text.index('import argparse'):]
        for word in ('backlog-append', 'backlog', 'todo', 'workspace:', 'project:'):
            self.assertNotIn(word, code, word)

    def test_the_table_is_valid_against_its_schema_and_supplier_comes_first(self):
        import jsonschema
        table = yaml.safe_load((SCRIPTS / 'dispatch-table.yml').read_text())
        jsonschema.Draft7Validator(json.loads((SCRIPTS / 'dispatch-table.schema.json').read_text())).validate(table)
        self.assertLess(table['artifacts']['notes']['order'], table['artifacts']['backlog']['order'])


class Invariant1(Base):
    def test_every_day_file_is_marked_or_held_exactly_once(self):
        self.day(D1)
        self.day(D2)
        report = self.dispatch([note('x', title='a', day=D1), note('y', ['todo', 'workspace:nope'], title='b', day=D2)],
                               [f'journal/{D1}.md', f'journal/{D2}.md'])
        self.assertEqual(report['marked'], [f'journal/{D1}.md'])
        self.assertEqual([h['day_file'] for h in report['held']], [f'journal/{D2}.md'])
        self.assertTrue(self.marked(D1))
        self.assertFalse(self.marked(D2))

    def test_zero_thought_day_file_is_marked_under_silent(self):
        self.day(D1)
        report = self.dispatch([], [f'journal/{D1}.md'])
        self.assertEqual(report['marked'], [f'journal/{D1}.md'])
        self.assertTrue(self.marked(D1))

    def test_a_closed_day_file_the_manifest_forgot_is_held_not_silently_skipped(self):
        self.day(D1)
        self.day(D2)
        report = self.dispatch([], [f'journal/{D1}.md'])
        self.assertEqual([h['day_file'] for h in report['held']], [f'journal/{D2}.md'])
        self.assertIn('not accounted for', report['held'][0]['failed'][0]['reason'])
        self.assertFalse(self.marked(D2))

    def test_a_held_unit_never_blocks_the_others_and_the_commit_lands_then_exits_non_zero(self):
        self.day(D1)
        self.day(D2)
        self.dispatch([note('x', title='a', day=D1), note('y', ['todo', 'workspace:nope'], title='b', day=D2)],
                      [f'journal/{D1}.md', f'journal/{D2}.md'])
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f'journal/{D2}.md', r.stderr)
        log = subprocess.run(['jj', 'log', '--no-graph', '-r', '@-', '-T', 'description'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('ingest(silent)', log)
        status = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('notes/b.md', status)

    def test_commit_rollback_leaves_files_unmarked_and_unheld(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        (self.run_dir / 'report.json').write_text(json.dumps(dict(json.loads((self.run_dir / 'report.json').read_text()), written=['notes/absent.md'])))
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.marked(D1))

    def test_clean_run_commits_and_exits_zero_and_no_op_run_stays_quiet(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertEqual(self.commit().returncode, 0)
        self.run_id = '2026-11-02-2'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()
        self.dispatch([], [])
        r = self.commit()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('no-op', r.stdout)


class Invariant2(Base):
    def test_the_open_day_is_routed_but_never_marked_or_held(self):
        self.day(TODAY)
        report = self.dispatch([note('x', ['todo', 'workspace:values'], title='a', day=TODAY)], [f'journal/{TODAY}.md'], mode='interactive')
        self.assertEqual(self.items()[0]['id'], 'a')
        self.assertEqual(report['marked'], [])
        self.assertFalse(self.marked(TODAY))
        self.assertEqual(report['held'], [])


class Invariant4(Base):
    def test_open_day_failures_are_still_reported_against_the_thought(self):
        self.day(TODAY)
        report = self.dispatch([note('x', ['todo', 'workspace:nope'], title='a', day=TODAY)], [], mode='interactive')
        self.assertEqual(report['held'], [])
        self.assertEqual(len(report['open_day_failed']), 1)
        self.assertEqual(report['open_day_failed'][0]['ref'], _ingest_keys.thought_ref(f'journal/{TODAY}', 'x'))
        self.assertIn('workspace:nope', report['open_day_failed'][0]['reason'])

    def test_every_failure_is_reported_with_ref_target_and_id(self):
        self.day(D1)
        report = self.dispatch([note('x', ['todo', 'workspace:nope'], title='a')], [f'journal/{D1}.md'])
        failure = report['held'][0]['failed'][0]
        self.assertEqual(failure['target'], {'container': 'workspace', 'artifact': 'backlog'})
        self.assertEqual(failure['ref'], _ingest_keys.thought_ref(f'journal/{D1}', 'x'))
        self.assertEqual(self.fm('a')['routed_to'], [{'container': 'vault', 'artifact': 'notes', 'name': 'vault'}])

    def test_missing_backlog_and_id_collision_are_failed_targets(self):
        self.day(D1)
        (self.tmp / 'values' / 'BACKLOG.yml').write_text(yaml.safe_dump({'items': [
            {'id': 'a', 'title': 'other', 'labels': [], 'added': '2026-01-01', 'source': 'journal/2020-01-01', 'state': 'open'}]}))
        report = self.dispatch([note('x', ['todo', 'workspace:values'], title='a')], [f'journal/{D1}.md'])
        self.assertIn('id collision', report['held'][0]['failed'][0]['reason'])
        (self.tmp / 'gaming' / 'BACKLOG.yml').unlink()
        self.day(D2)
        report = self.dispatch([note('y', ['todo', 'workspace:gaming'], title='b', day=D2)], [f'journal/{D2}.md'])
        by_day = {h['day_file']: h['failed'] for h in report['held']}
        self.assertIn('no backlog', by_day[f'journal/{D2}.md'][0]['reason'])

    def test_an_unparseable_existing_note_fails_only_its_own_thought(self):
        self.day(D1)
        body = 'existing'
        (self.vault / 'notes' / 'bad.md').write_text(f'---\ntitle: "un"terminated"\nsource: journal/{D1}\n---\n\n{body}\n')
        report = self.dispatch([note(body, ['todo', 'workspace:values'], title='bad-one'), note('fine', title='fine')], [f'journal/{D1}.md'])
        self.assertIn('notes/fine.md', report['written'])
        self.assertEqual(self.items(), [])
        self.assertEqual(len(report['held'][0]['failed']), 1)
        self.assertEqual(report['held'][0]['failed'][0]['target']['artifact'], 'notes')

    def test_a_note_with_no_matching_rule_is_not_dropped(self):
        self.day(D1)
        self.save_lib({'rules': []})
        report = self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertIn('no routing rule', report['held'][0]['failed'][0]['reason'])

    def test_no_id_supplier_means_no_id_source(self):
        self.day(D1)
        self.save_lib({'rules': [RULES['rules'][3]]})
        report = self.dispatch([note('x', ['todo'], title='a')], [f'journal/{D1}.md'])
        self.assertIn('no id source', report['held'][0]['failed'][0]['reason'])


class Invariant5(Base):
    def filed(self, labels=('todo', 'workspace:values')):
        self.day(D1)
        self.dispatch([note('x', list(labels), title='t')], [f'journal/{D1}.md'])

    def test_silent_takes_the_stored_labels_and_never_changes_them(self):
        self.filed()
        self.day(D2)
        report = self.dispatch([note('x', ['idea'], title='t')], [])
        self.assertEqual(self.fm('t')['labels'], ['todo', 'workspace:values'])
        self.assertEqual(report['routed'][0]['labels'], ['todo', 'workspace:values'])
        self.assertEqual(len(self.items()), 1)

    def test_a_gate_edit_changes_stored_labels_frontmatter_only(self):
        self.filed()
        before = self.body('t')
        report = self.dispatch([note('x', ['todo', 'workspace:gaming'], title='t')], [], mode='interactive')
        self.assertEqual(self.fm('t')['labels'], ['todo', 'workspace:gaming'])
        self.assertEqual(self.body('t'), before)
        self.assertIn('notes/t.md', report['rewritten'])
        self.assertEqual(self.items('gaming')[0]['id'], 't')

    def test_gate_route_proposes_the_stored_labels(self):
        self.filed()
        r = self.script('dispatch-targets', 'route', self.vault, self.manifest([note('x', ['idea'], title='t')]))
        out = json.loads(r.stdout)[0]
        self.assertEqual(out['labels'], ['todo', 'workspace:values'])
        self.assertTrue(out['already_filed'])


class ReRuns(Base):
    def test_a_retry_is_safe(self):
        self.day(D1)
        n = [note('x', ['todo', 'workspace:values'], title='t')]
        self.dispatch(n, [f'journal/{D1}.md'])
        body = (self.vault / 'notes' / 't.md').read_text()
        items = self.items()
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual((self.vault / 'notes' / 't.md').read_text(), body)
        self.assertEqual(self.items(), items)
        self.assertEqual(report['skipped'], ['notes/t.md'])
        self.assertEqual(report['written'], [])
        self.assertEqual(report['rewritten'], [])
        self.assertEqual(len(self.fm('t')['routed_to']), 2)

    def test_routed_to_is_unioned_and_never_removed(self):
        self.day(D1)
        self.dispatch([note('x', ['todo', 'workspace:values'], title='t')], [f'journal/{D1}.md'])
        (self.tmp / 'values' / 'BACKLOG.yml').unlink()
        report = self.dispatch([note('x', ['todo', 'workspace:values'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(len(self.fm('t')['routed_to']), 2)
        self.assertEqual(len(report['held']), 1)

    def test_outcome_skips_non_supplier_targets_and_is_neither_success_nor_failure(self):
        self.day(D1)
        n = [note('x', ['todo', 'workspace:values'], title='t')]
        self.dispatch(n, [f'journal/{D1}.md'])
        (self.tmp / 'values' / 'BACKLOG.yml').write_text('items: []\n')
        self.assertEqual(self.script('note-outcome', self.vault, 't', 'done', '--resolved', '2026-02-01').returncode, 0)
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(self.items(), [])
        self.assertEqual(report['held'], [])
        self.assertEqual(report['routed'][0]['targets'], [{'container': 'vault', 'artifact': 'notes', 'name': 'vault'}])

    def test_held_day_clears_once_the_cause_is_fixed(self):
        self.day(D1)
        n = [note('x', ['todo', 'workspace:new'], title='t')]
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertTrue(report['held'])
        d = self.tmp / 'new'
        d.mkdir()
        (d / 'BACKLOG.yml').write_text('items: []\n')
        self.rows.append({'name': 'new', 'kind': 'workspace', 'path': str(d), 'artifacts': {'backlog': 'BACKLOG.yml'}})
        self.save_lib()
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(report['held'], [])
        self.assertEqual(self.items('new')[0]['id'], 't')
        self.assertTrue(self.marked(D1))


class OddNotes(Base):
    def filed(self, frontmatter):
        (self.vault / 'notes' / 'odd.md').write_text(f'---\ntitle: T\nsource: journal/{D1}\n{frontmatter}---\n\nodd body\n')

    def only_its_own_thought_fails(self, report):
        self.assertIn('notes/fine.md', report['written'])
        self.assertEqual(len(report['held'][0]['failed']), 1)

    def test_malformed_routed_to_fails_only_its_own_thought(self):
        self.day(D1)
        for shape in ('routed_to:\n- foo\n', 'routed_to: nope\n', 'routed_to:\n- {container: x}\n'):
            with self.subTest(shape):
                self.filed(shape + 'labels: [todo, workspace:values]\n')
                report = self.dispatch([note('odd body', ['todo', 'workspace:values'], title='o'), note('fine', title='fine')], [f'journal/{D1}.md'])
                self.assertEqual(report['held'][0]['day_file'], f'journal/{D1}.md')
                self.assertIn('malformed', report['held'][0]['failed'][0]['reason'])
                (self.vault / 'notes' / 'fine.md').unlink()
                (self.tmp / 'values' / 'BACKLOG.yml').write_text('items: []\n')

    def test_non_list_labels_fail_only_their_own_thought(self):
        self.day(D1)
        self.filed('labels: todo\n')
        report = self.dispatch([note('odd body', ['todo'], title='o'), note('fine', title='fine')], [f'journal/{D1}.md'])
        self.only_its_own_thought_fails(report)
        self.assertIn('labels', report['held'][0]['failed'][0]['reason'])

    def test_leading_blank_lines_are_not_an_abort_and_still_dedup(self):
        self.day(D1)
        n = [note('\n\nfoo bar', title='t')]
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(report['written'], ['notes/t.md'])
        self.assertEqual(self.dispatch(n, [f'journal/{D1}.md'])['skipped'], ['notes/t.md'])
        self.assertEqual([p.name for p in (self.vault / 'notes').iterdir()], ['t.md'])

    def test_crlf_body_is_stored_verbatim_and_dedups(self):
        self.day(D1)
        n = [note('a\r\nb', title='t')]
        self.assertEqual(self.dispatch(n, [f'journal/{D1}.md'])['written'], ['notes/t.md'])
        with open(self.vault / 'notes' / 't.md', newline='') as f:
            self.assertIn('a\r\nb', f.read())
        self.assertEqual(self.dispatch(n, [f'journal/{D1}.md'])['skipped'], ['notes/t.md'])
        report = self.script('note-outcome', self.vault, 't', 'done', '--resolved', '2026-02-01')
        self.assertEqual(report.returncode, 0, report.stderr)
        with open(self.vault / 'notes' / 't.md', newline='') as f:
            self.assertIn('a\r\nb', f.read())


class Sources(Base):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.tmp / 'src-a', self.tmp / 'src-b'
        for d in (self.a, self.b):
            d.mkdir()
            (d / 'in.md').write_text('content\n')
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': [
            {'path': str(self.a), 'track': 'destructive', 'lens': ['idea']},
            {'path': str(self.b), 'track': 'destructive', 'lens': ['idea']}]}))

    def run_sources(self, source_a_labels):
        moves = [{'from': str(d / 'in.md'), 'date': '2026-07-05'} for d in (self.a, self.b)]
        notes = [dict(note('from a', source_a_labels, title='a'), source=f'r {self.a} @1'),
                 dict(note('from b', title='b'), source=f'r {self.b} @1')]
        r = self.script('dispatch-targets', 'run', self.vault, self.manifest(notes, archive_moves=moves), '--mode', 'silent', '--no-journal')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_one_failed_source_never_blocks_another(self):
        report = self.run_sources(['todo', 'workspace:nope'])
        self.assertEqual(len(report['moved']), 1)
        self.assertTrue((self.a / 'in.md').exists())
        self.assertFalse((self.b / 'in.md').exists())
        self.assertEqual(len(report['held']), 1)
        self.assertIn(str(self.a), report['held'][0]['source'])

    def test_all_sources_succeeding_all_move(self):
        self.assertEqual(len(self.run_sources(['idea'])['moved']), 2)


class NoteOutcome(Base):
    def setUp(self):
        super().setUp()
        (self.vault / 'notes' / 'n.md').write_text('---\ntitle: T\nlabels: [todo]\ncreated: 2026-01-01\ncaptured: 2026-01-01\nsource: journal/2026-01-01\n---\n\nbody here\n')

    def test_records_frontmatter_only_keeping_types_and_order(self):
        before = self.body('n')
        r = self.script('note-outcome', self.vault, 'n', 'done', '--resolved', '2026-02-01')
        self.assertEqual(json.loads(r.stdout), {'status': 'recorded', 'outcome': 'done'})
        self.assertEqual(self.body('n'), before)
        data = self.fm('n')
        self.assertEqual(data['resolved'], datetime.date(2026, 2, 1))
        self.assertIsInstance(data['created'], datetime.date)
        self.assertEqual(list(data)[:2], ['title', 'labels'])

    def test_identical_is_a_noop_conflicting_is_an_error_missing_is_an_error(self):
        self.script('note-outcome', self.vault, 'n', 'done', '--resolved', '2026-02-01')
        same = self.script('note-outcome', self.vault, 'n', 'done', '--resolved', '2026-02-01')
        self.assertEqual(json.loads(same.stdout), {'status': 'exists'})
        for args in (['n', 'dropped', '--resolved', '2026-02-01'], ['n', 'done', '--resolved', '2026-03-01'], ['absent', 'done', '--resolved', '2026-02-01']):
            r = self.script('note-outcome', self.vault, *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)

    def test_bad_input_and_path_escape_are_refused(self):
        for args in (['n', 'maybe', '--resolved', '2026-02-01'], ['n', 'done', '--resolved', 'soon'], ['../x', 'done', '--resolved', '2026-02-01'], ['n', 'done']):
            r = self.script('note-outcome', self.vault, *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)


class Status(Base):
    def status(self):
        r = self.script('ingest-status', self.vault)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_first_line_is_what_the_nightly_wrapper_reads(self):
        self.day(D1)
        self.assertEqual(self.status().split('\n')[0], f'pending closed day-files: 1 ({D1}.md)')

    def test_held_units_are_listed_with_their_reason_until_cleared(self):
        self.day(D1)
        n = [note('x', ['todo', 'workspace:nope'], title='t')]
        self.dispatch(n, [f'journal/{D1}.md'])
        self.assertIn('workspace:nope', self.status())
        self.assertIn(f'journal/{D1}.md', self.status())

    def test_hand_removed_item_is_an_anomaly_until_closed(self):
        self.day(D1)
        self.dispatch([note('x', ['todo', 'workspace:values'], title='t')], [f'journal/{D1}.md'])
        self.assertNotIn('backlog item gone', self.status())
        (self.tmp / 'values' / 'BACKLOG.yml').write_text('items: []\n')
        self.assertIn('backlog item gone', self.status())
        self.script('note-outcome', self.vault, 't', 'dropped', '--resolved', '2026-02-01')
        self.assertNotIn('backlog item gone', self.status())

    def orphan(self, extra=''):
        (self.vault / 'notes' / 'o.md').write_text(f'---\ntitle: O\nlabels: [todo]\nsource: journal/2020-01-01\n{extra}---\n\nb\n')

    def test_orphaned_actionable_is_flagged_and_closed_notes_are_not(self):
        self.orphan()
        self.assertIn('orphaned actionables', self.status())
        self.orphan('outcome: dropped\n')
        self.assertNotIn('orphaned actionables', self.status())
        self.orphan('handled: [x]\n')
        self.assertNotIn('orphaned actionables', self.status())

    def test_note_from_an_unmarked_day_is_not_an_orphan_yet(self):
        self.day('2020-01-01')
        self.orphan()
        self.assertNotIn('orphaned actionables', self.status())

    def test_a_label_that_only_fails_to_resolve_is_still_an_orphan(self):
        (self.vault / 'notes' / 'o.md').write_text('---\ntitle: O\nlabels: [todo, workspace:nope]\nsource: journal/2020-01-01\n---\n\nb\n')
        self.assertIn('orphaned actionables', self.status())

    def test_unparseable_note_is_an_anomaly_not_a_crash(self):
        (self.vault / 'notes' / 'bad.md').write_text('---\ntitle: "un"terminated"\n---\n\nb\n')
        self.assertIn('unparseable notes: 1', self.status())

    def test_loop_guard_is_derived_from_the_rules(self):
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': [
            {'path': '/tmp/x', 'track': 'destructive', 'lens': ['todo', 'idea']},
            {'path': '/tmp/y', 'track': 'destructive', 'lens': ['workspace:values']}]}))
        out = self.status()
        self.assertIn('lens label todo is outbound', out)
        self.assertIn('lens label workspace:values is outbound', out)
        self.assertNotIn('lens label idea', out)

    def registry(self, sources):
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': sources}))

    def test_a_lens_that_is_not_a_list_is_reported_not_missed(self):
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': 'todo'}])
        self.assertIn('not a list of labels', self.status())
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['idea', 5]}])
        self.assertIn('not a list of labels', self.status())

    def test_malformed_registry_entries_are_reported_not_crashes(self):
        for sources in (['foo'], [{'track': 'destructive'}], [{'path': '/tmp/x'}], 'x'):
            (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': sources}))
            self.assertIn('malformed registry', self.status())

    def test_absent_rules_are_stated_not_silently_clean(self):
        (self.lib / 'data' / 'routing.yml').unlink()
        self.assertIn('loop guard not checked', self.status())

    def test_a_none_term_makes_nothing_outbound(self):
        self.save_lib({'rules': [{'match': [{'none': ['x']}], 'to': [{'container': 'kernel', 'artifact': 'backlog'}]}]})
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['x']}])
        self.assertNotIn('outbound', self.status())

    def test_the_catch_all_alone_makes_nothing_outbound(self):
        self.save_lib({'rules': [RULES['rules'][0]]})
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': [{'path': '/tmp/x', 'track': 'destructive', 'lens': ['todo']}]}))
        self.assertNotIn('outbound', self.status())

    def test_duplicates_and_invalid_backlogs_surface(self):
        (self.tmp / 'values' / 'BACKLOG.yml').write_text('items: [{id: BAD}]\n')
        self.assertIn('invalid backlogs', self.status())

    def test_no_lib_is_a_message_not_a_crash(self):
        env = {k: v for k, v in os.environ.items() if k != 'AGENT_LIB'}
        r = subprocess.run([str(SCRIPTS / 'ingest-status'), str(self.vault)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('reconciliation skipped', r.stdout)


class FailLoud(Base):
    """Nightly job, v2.2: success keys off a completed report; nothing on the unattended path hangs; recovery."""

    def report(self):
        return json.loads((self.run_dir / 'report.json').read_text())

    def committed_report(self):
        rel = (self.run_dir / 'report.json').relative_to(self.vault)
        return json.loads(subprocess.run(['jj', 'file', 'show', '-r', '@-', str(rel)], cwd=self.vault,
                                         capture_output=True, text=True, check=True).stdout)

    def next_run(self, n):
        self.run_id = f'2026-11-02-{n}'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()

    def recover(self):
        r = self.script('commit-run', '--recover', self.vault)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['recovered']

    def test_a_clean_commit_carries_completed(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertNotIn('completed', self.report())
        self.assertEqual(self.commit().returncode, 0)
        self.assertIs(self.committed_report()['completed'], True)
        self.assertIs(self.report()['completed'], True)

    def test_a_held_run_is_completed_and_still_held(self):
        self.day(D1)
        self.dispatch([note('y', ['todo', 'workspace:nope'], title='b')], [f'journal/{D1}.md'])
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertIs(self.committed_report()['completed'], True)
        self.assertTrue(self.report()['held'])

    def test_a_no_op_run_is_completed(self):
        self.dispatch([], [])
        r = self.commit()
        self.assertIn('no-op', r.stdout)
        self.assertIs(self.report()['completed'], True)

    def test_a_rolled_back_commit_is_not_completed(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        (self.run_dir / 'report.json').write_text(json.dumps(dict(self.report(), written=['notes/absent.md'])))
        self.assertNotEqual(self.commit().returncode, 0)
        self.assertIs(self.report()['completed'], False)
        self.next_run(2)
        self.assertIsNone(self.recover())  # a rollback is not a kill: its markers are already gone

    def test_a_run_killed_before_its_commit_is_recovered_by_the_next(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])  # written and marked; killed before commit-run
        killed = self.run_id
        self.next_run(2)
        self.assertEqual(self.recover(), killed)
        log = subprocess.run(['jj', 'log', '--no-graph', '-r', '@-', '-T', 'description'], cwd=self.vault,
                             capture_output=True, text=True).stdout
        self.assertIn(f'ingest(recovered): {killed}', log)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('notes/a.md', shown)
        self.assertIn(f'journal/{D1}.md', shown)
        self.assertIn(f'{killed}/report.json', shown)
        self.assertIn(killed, (self.vault / 'CHANGELOG.md').read_text())
        self.assertIsNone(self.recover())
        r = self.script('dispatch-targets', 'run', self.vault, self.manifest([], []), '--mode', 'silent', '--recovered', killed)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.report()['recovered'], killed)

    def test_nothing_to_recover_without_an_incomplete_dirty_run(self):
        self.assertIsNone(self.recover())
        self.dispatch([], [])
        self.commit()  # a completed no-op leaves its run dir uncommitted
        (self.vault / 'notes' / 'hand-edit.md').write_text('mine\n')
        self.next_run(2)
        self.assertIsNone(self.recover())
        self.assertTrue((self.vault / 'notes' / 'hand-edit.md').exists())

    def test_an_open_day_file_and_an_aborted_run_are_not_a_recovery(self):
        (self.run_dir / 'run.json').write_text('{}')  # aborted before dispatch: no report
        self.day(TODAY, 'captured this morning\n')
        (self.vault / 'notes' / 'hand-edit.md').write_text('mine\n')
        self.next_run(2)
        self.assertIsNone(self.recover())
        st = subprocess.run(['jj', 'diff', '--name-only'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn(f'journal/{TODAY}.md', st)
        self.assertIn('notes/hand-edit.md', st)

    def test_recovery_commits_only_the_killed_runs_own_paths(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.day(TODAY, 'open day\n')
        killed = self.run_id
        self.next_run(2)
        self.assertEqual(self.recover(), killed)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertNotIn(f'journal/{TODAY}.md', shown)
        self.assertIn('notes/a.md', shown)

    def test_a_kill_after_completed_was_written_but_before_the_commit_is_recovered(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        (self.run_dir / 'report.json').write_text(json.dumps(dict(self.report(), completed=True)))  # then killed
        killed = self.run_id
        self.next_run(2)
        self.assertEqual(self.recover(), killed)
        self.assertTrue(self.marked(D1))
        self.assertIsNone(self.recover())

    def test_a_hung_supplier_batch_holds_its_units_instead_of_aborting(self):
        scripts = self.tmp / 'scripts'
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns('tests', '__pycache__'))
        real = scripts / 'file-notes.real'
        (scripts / 'file-notes').rename(real)
        (scripts / 'file-notes').write_text(f'#!/bin/sh\n[ "$1" = write ] && exec sleep 60\nexec "{real}" "$@"\n')
        (scripts / 'file-notes').chmod(0o755)
        self.day(D1)
        r = subprocess.run([str(scripts / 'dispatch-targets'), 'run', str(self.vault),
                            str(self.manifest([note('x', title='a')], [f'journal/{D1}.md'])), '--mode', 'silent'],
                           capture_output=True, text=True, env=dict(self.env(), VAULT_INGEST_CALL_TIMEOUT='1'), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        held = json.loads(r.stdout)['held']
        self.assertEqual([h['day_file'] for h in held], [f'journal/{D1}.md'])
        self.assertIn('timed out', held[0]['failed'][0]['reason'])
        self.assertFalse(self.marked(D1))

    def test_a_hung_writer_is_a_failed_target_and_its_unit_is_held(self):
        hang = self.lib / 'functions' / 'backlog-append'
        hang.write_text('#!/bin/sh\nsleep 60 &\nsleep 60\n')  # the grandchild holds the pipes if only the child dies
        self.day(D1)
        start = datetime.datetime.now()
        r = subprocess.run([str(SCRIPTS / 'dispatch-targets'), 'run', str(self.vault),
                            str(self.manifest([note('y', ['todo', 'workspace:values'], title='b')], [f'journal/{D1}.md'])),
                            '--mode', 'silent'], capture_output=True, text=True,
                           env=dict(self.env(), VAULT_INGEST_CALL_TIMEOUT='1'), timeout=30)
        self.assertLess((datetime.datetime.now() - start).total_seconds(), 20)
        self.assertEqual(r.returncode, 0, r.stderr)
        held = json.loads(r.stdout)['held']
        self.assertEqual([h['day_file'] for h in held], [f'journal/{D1}.md'])
        self.assertIn('timed out', held[0]['failed'][0]['reason'])
        self.assertFalse(self.marked(D1))

    def test_a_raise_part_way_through_finish_still_writes_a_recoverable_report(self):
        # F3: mark -> advance -> archive used to raise before report.json, so --recover never saw the run.
        self.day(D1)
        (self.vault / 'notes' / 'a.md').write_text('---\ntitle: "a"\n---\nbody\n')
        plan = self.tmp / 'plan.json'
        plan.write_text(json.dumps({'report_path': str(self.run_dir / 'report.json'), 'report': {'written': ['notes/a.md']},
                                    'mark_ingested': [f'journal/{D1}.md', 'journal/1999-01-01.md'],  # the 2nd is missing
                                    'advance': [], 'archive_moves': []}))
        r = self.script('file-notes', 'finish', self.vault, plan)
        self.assertNotEqual(r.returncode, 0)
        report = json.loads((self.run_dir / 'report.json').read_text())
        self.assertEqual(report['marked'], [f'journal/{D1}.md'])
        self.assertNotIn('completed', report)
        self.assertTrue(self.marked(D1))
        self.assertEqual(self.recover(), self.run_id)

    def test_the_run_deadline_bounds_the_calls_sum_and_holds_the_unit(self):
        # F1: a caller with its own timeout (claude's Bash tool) can bound the whole command, not one call.
        hang = self.lib / 'functions' / 'backlog-append'
        hang.write_text('#!/bin/sh\nsleep 60\n')
        self.day(D1)
        start = datetime.datetime.now()
        r = subprocess.run([str(SCRIPTS / 'dispatch-targets'), 'run', str(self.vault),
                            str(self.manifest([note('y', ['todo', 'workspace:values'], title='b')], [f'journal/{D1}.md'])),
                            '--mode', 'silent'], capture_output=True, text=True,
                           env=dict(self.env(), VAULT_INGEST_CALL_TIMEOUT='60', VAULT_INGEST_RUN_DEADLINE='2'), timeout=30)
        self.assertLess((datetime.datetime.now() - start).total_seconds(), 20)
        self.assertEqual(r.returncode, 0, r.stderr)
        held = json.loads(r.stdout)['held']
        self.assertEqual([h['day_file'] for h in held], [f'journal/{D1}.md'])
        self.assertIn('timed out', held[0]['failed'][0]['reason'])
        self.assertFalse(self.marked(D1))

    def test_sigterm_kills_the_running_writer_group(self):
        # F1: the writers run in their own sessions; killing dispatch-targets must not leave one running.
        pids = self.tmp / 'writer-pids'
        hang = self.lib / 'functions' / 'backlog-append'
        hang.write_text(f'#!/bin/sh\necho $$ >>{pids}\nsleep 60 &\necho $! >>{pids}\nsleep 60\n')
        self.day(D1)
        proc = subprocess.Popen([str(SCRIPTS / 'dispatch-targets'), 'run', str(self.vault),
                                 str(self.manifest([note('y', ['todo', 'workspace:values'], title='b')], [f'journal/{D1}.md'])),
                                 '--mode', 'silent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env())
        for _ in range(100):
            if pids.exists() and len(pids.read_text().split()) == 2:
                break
            time.sleep(0.1)
        writers = [int(p) for p in pids.read_text().split()]
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 128 + signal.SIGTERM)
        time.sleep(0.5)
        for pid in writers:
            with self.assertRaises(ProcessLookupError, msg=f'writer {pid} survived'):
                os.kill(pid, 0)


if __name__ == '__main__':
    unittest.main()
