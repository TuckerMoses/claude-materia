"""The Ingest run sequence's invariants as tests. Real scripts in a throwaway copy of the plugin, a throwaway jj vault
with its own label bank and routing file, and fake adapters for the seam. Needs nothing outside the plugin: every
child runs with AGENT_LIB removed from its environment.

Run from anywhere:
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

REAL_SCRIPTS = Path(__file__).resolve().parent.parent
PLUGIN = REAL_SCRIPTS.parents[2]
sys.path.insert(0, str(PLUGIN / 'scripts'))
import _ingest_keys  # noqa: E402
import _routing  # noqa: E402

TODAY = datetime.date.today().isoformat()
D1, D2 = '2026-01-02', '2026-01-03'
ACTION = {'any': ['todo', 'session-seed', 'delegated']}
NOTES_ONLY = {'targets': {'notes': {'adapter': 'notes'}}, 'rules': [{'match': ['*'], 'to': ['notes']}]}
SEED = PLUGIN / 'skills' / 'vault' / 'assets' / 'labels.yml'
EXTRA = {'workspace:values': {'when_to_apply': 'The values workspace.', 'status': 'active', 'origin': 'imported'},
         'workspace:gaming': {'when_to_apply': 'The gaming workspace.', 'status': 'active', 'origin': 'imported'}}

# Fake adapters, written into the plugin copy. Each speaks the adapter interface (see adapters/notes).
RECORD = '''#!{py}
import json, sys
req = json.load(sys.stdin)
with open(req['params']['log'], 'a') as f:
    f.write(json.dumps(req) + '\\n')
print(json.dumps({{'status': 'delivered', 'landed': {{'id': req['thought'].get('id')}}}}))
'''
FAIL = '''#!{py}
import json, sys
req = json.load(sys.stdin)
print(json.dumps({{'status': 'failed', 'reason': req['params'].get('reason', 'refused by the fake adapter')}}))
'''
CRASH = '#!/bin/sh\necho "fake adapter crashed" >&2\nexit 1\n'
GARBAGE = '#!/bin/sh\ncat >/dev/null\necho "not json"\n'
ABORTS = '#!/bin/sh\ncat >/dev/null\necho "ABORT fake iron-rule refusal" >&2\nexit 2\n'
HANG = '#!/bin/sh\nsleep 60 &\nsleep 60\n'  # the grandchild holds the pipes if only the child dies


def note(body, labels=('idea',), day=D1, title=None, **extra):
    return dict({'title': title or body[:40], 'labels': list(labels), 'created': TODAY, 'captured': day,
                 'source': f'journal/{day}', 'body': body}, **extra)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp)
        plugin = self.tmp / 'plugin'
        shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns('tests', '__pycache__', 'docs', '.git'))
        self.scripts = plugin / 'skills' / 'ingest' / 'scripts'
        for name, text in (('record', RECORD), ('fail', FAIL), ('crash', CRASH), ('garbage', GARBAGE),
                           ('aborts', ABORTS), ('hang', HANG)):
            self.adapter(name, text.format(py=sys.executable) if '{py}' in text else text)
        self.vault = self.tmp / 'vault'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'journal').mkdir()
        (self.vault / '_machine' / 'logs' / 'ingest').mkdir(parents=True)
        (self.vault / '_machine' / 'ingest_paths.yml').write_text('sources: []\n')
        bank = yaml.safe_load(SEED.read_text())
        bank['labels'].update(EXTRA)
        (self.vault / '_machine' / 'labels.yml').write_text(yaml.safe_dump(bank, sort_keys=False))
        shutil.copy(PLUGIN / 'skills' / 'vault' / 'assets' / 'label-proposals.yml', self.vault / '_machine' / 'label-proposals.yml')
        subprocess.run(['jj', 'git', 'init', str(self.vault)], capture_output=True, check=True)
        self.log = self.tmp / 'delivered.jsonl'
        self.save_routing(NOTES_ONLY)
        self.run_id = '2026-11-02-1'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()

    def adapter(self, name, text):
        p = self.scripts / 'adapters' / name
        p.write_text(text)
        p.chmod(0o755)

    def save_routing(self, routing):
        (self.vault / '_machine' / 'routing.yml').write_text(yaml.safe_dump(routing, sort_keys=False))

    def route_actions_to(self, adapter, **params):
        """The catch-all to notes, plus action labels to an `inbox` target using ADAPTER."""
        params.setdefault('log', str(self.log))
        self.save_routing({'targets': {'notes': {'adapter': 'notes'}, 'inbox': {'adapter': adapter, 'params': params}},
                           'rules': [{'match': ['*'], 'to': ['notes']}, {'match': [ACTION], 'to': ['inbox']}]})

    def delivered(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k != 'AGENT_LIB'}
        env.update(extra)
        return env

    def script(self, name, *args, **env):
        return subprocess.run([str(self.scripts / name), *map(str, args)], capture_output=True, text=True,
                              env=self.env(**env))

    def day(self, date, text='some day text\n'):
        p = self.vault / 'journal' / f'{date}.md'
        p.write_text(text)
        return p

    def manifest(self, notes, marks=None, name='proposals.json', **extra):
        path = self.run_dir / name
        path.write_text(json.dumps(dict({'notes': notes, 'mark_ingested': marks if marks is not None else [], 'advance': [], 'archive_moves': []}, **extra)))
        return path

    def run_dispatch(self, notes, marks=None, mode='silent', **extra):
        name = 'confirmed-manifest.json' if mode == 'interactive' else 'proposals.json'
        return self.script('dispatch-targets', 'run', self.vault, self.manifest(notes, marks, name=name, **extra), '--mode', mode)

    def dispatch(self, notes, marks=None, mode='silent', **extra):
        r = self.run_dispatch(notes, marks, mode, **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

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

    def notes(self):
        return sorted(p.name for p in (self.vault / 'notes').iterdir())


NOTES_ENTRY = {'target': 'notes', 'adapter': 'notes'}


class Keys(unittest.TestCase):
    def test_trailing_newlines_do_not_change_the_key(self):
        self.assertEqual(_ingest_keys.thought_ref('s', 'body'), _ingest_keys.thought_ref('s', 'body\n\n'))
        self.assertEqual(_ingest_keys.body_md5('body\n'), _ingest_keys.body_md5('body'))
        self.assertNotEqual(_ingest_keys.body_md5('body '), _ingest_keys.body_md5('body'))
        self.assertTrue(_ingest_keys.thought_ref('journal/x', 'b').startswith('journal/x+'))

    def test_day_md5_is_of_the_bytes(self):
        import hashlib
        with tempfile.NamedTemporaryFile('wb') as f:
            f.write(b'\xff\n')
            f.flush()
            self.assertEqual(_ingest_keys.day_md5(f.name), hashlib.md5(b'\xff\n').hexdigest())


class Matching(unittest.TestCase):
    """The match semantics the vault's routing keeps from the routing it replaces."""

    def routing(self, rules, targets=('notes', 'a', 'b')):
        data = {'targets': {t: {'adapter': 'notes' if t == 'notes' else 'record'} for t in targets}, 'rules': rules}
        return _routing.Routing(data)

    def test_terms(self):
        r = self.routing([])
        h = _routing.holds
        self.assertTrue(h('*', []))
        self.assertTrue(h('todo', ['idea', 'todo']))
        self.assertFalse(h('todo', ['todos']))
        self.assertTrue(h('project:*', ['project:x']))
        self.assertFalse(h('project:*', ['workspace:x']))
        self.assertTrue(h('a*c', ['abbc']))
        self.assertFalse(h('a.c', ['abc']))  # only * is special
        self.assertTrue(h({'any': ['x', 'todo']}, ['todo']))
        self.assertFalse(h({'any': ['x', 'y']}, ['todo']))
        self.assertTrue(h({'none': ['project:*']}, ['todo']))
        self.assertFalse(h({'none': ['project:*', 'z']}, ['z']))
        self.assertEqual(r.route(['x']), [])

    def test_every_rule_that_holds_delivers_once_per_target_notes_first(self):
        r = self.routing([{'match': [ACTION], 'to': ['a', 'b']}, {'match': ['*'], 'to': ['notes', 'a']},
                          {'match': ['todo', {'none': ['project:*']}], 'to': ['b']}])
        self.assertEqual(r.route(['todo']), ['notes', 'a', 'b'])
        self.assertEqual(r.route(['todo', 'project:p']), ['notes', 'a', 'b'])
        self.assertEqual(r.route(['idea']), ['notes', 'a'])

    def test_outbound_is_derived_from_rules_that_leave_the_vault(self):
        r = self.routing([{'match': ['*'], 'to': ['notes']}, {'match': [ACTION, 'workspace:*', {'none': ['x']}], 'to': ['a']}])
        self.assertTrue(r.is_outbound('todo'))
        self.assertTrue(r.is_outbound('workspace:values'))
        self.assertFalse(r.is_outbound('x'))
        self.assertFalse(r.is_outbound('idea'))

    def test_the_template_is_notes_only_and_valid(self):
        vault = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, vault)
        (vault / '_machine').mkdir()
        shutil.copy(PLUGIN / 'skills' / 'vault' / 'assets' / 'routing.yml', vault / '_machine' / 'routing.yml')
        r = _routing.load(vault)
        self.assertEqual(r.targets, {'notes': {'adapter': 'notes'}})
        self.assertEqual(r.route([]), ['notes'])
        self.assertEqual(r.outbound_patterns(), set())

    def test_the_rule_shape_is_what_label_bank_rename_rewrites(self):
        import _label_bank
        data = {'targets': {'notes': {'adapter': 'notes'}}, 'rules': [{'match': ['old', {'any': ['old']}], 'to': ['notes']}]}
        self.assertEqual(_label_bank._routing(data, 'old', 'new')['rules'][0]['match'], ['new', {'any': ['new']}])


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
        self.assertEqual(self.fm('t')['related'], ['[[x]]'])

    def test_body_is_verbatim(self):
        self.day(D1)
        body = 'line one\n\n  indented: "q" — dash\n---\nafter a rule\n'
        self.dispatch([note(body, title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.body('t').lstrip('\n'), body)

    def test_same_title_twice_gets_a_second_slug(self):
        self.day(D1)
        report = self.dispatch([note('one', title='t'), note('two', title='t')], [f'journal/{D1}.md'])
        self.assertEqual(report['written'], ['notes/t.md', 'notes/t-2.md'])

    def confined(self, label, manifest):
        before = self.notes()
        path = self.manifest(**manifest)
        r = self.script('dispatch-targets', 'run', self.vault, path, '--mode', 'silent')
        self.assertNotEqual(r.returncode, 0, label)
        self.assertEqual(self.notes(), before, label)

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

    def test_the_notes_adapter_speaks_the_adapter_interface(self):
        thought = dict(note('direct', title='d'), ref='r')
        request = json.dumps({'target': 'notes', 'params': {}, 'thought': thought})
        r = subprocess.run([str(self.scripts / 'adapters' / 'notes'), str(self.vault)], input=request,
                           capture_output=True, text=True, env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'status': 'delivered', 'landed': {
            'slug': 'd', 'path': 'notes/d.md', 'status': 'written', 'outcome': None}})
        again = subprocess.run([str(self.scripts / 'adapters' / 'notes'), str(self.vault)], input=request,
                               capture_output=True, text=True, env=self.env())
        self.assertEqual(json.loads(again.stdout)['landed']['status'], 'skipped')
        empty = json.dumps({'target': 'notes', 'params': {}, 'thought': dict(thought, body=' ')})
        r = subprocess.run([str(self.scripts / 'adapters' / 'notes'), str(self.vault)], input=empty,
                           capture_output=True, text=True, env=self.env())
        self.assertEqual(r.returncode, 2)
        self.assertIn('iron rule', r.stderr)


class Routing(Base):
    def test_the_notes_target_files_and_records_itself_in_routed_to(self):
        self.day(D1)
        report = self.dispatch([note('Do the thing', ['todo'], title='Do the thing')], [f'journal/{D1}.md'])
        self.assertEqual(report['written'], ['notes/do-the-thing.md'])
        self.assertEqual(self.fm('do-the-thing')['routed_to'], [NOTES_ENTRY])
        self.assertEqual(report['held'], [])
        self.assertTrue(self.marked(D1))

    def test_multicast_to_notes_and_an_adapter_with_the_note_slug_as_id(self):
        self.route_actions_to('record', extra='p')
        self.day(D1)
        self.dispatch([note('Do the thing', ['todo', 'workspace:values'], title='Do the thing')], [f'journal/{D1}.md'])
        [req] = self.delivered()
        self.assertEqual(req['target'], 'inbox')
        self.assertEqual(req['params'], {'log': str(self.log), 'extra': 'p'})
        thought = req['thought']
        self.assertEqual(thought['id'], 'do-the-thing')
        self.assertEqual(thought['source'], f'journal/{D1}')
        self.assertEqual(thought['captured'], D1)
        self.assertEqual(thought['body'], 'Do the thing')
        self.assertEqual(thought['labels'], ['todo', 'workspace:values'])
        self.assertEqual(thought['ref'], _ingest_keys.thought_ref(f'journal/{D1}', 'Do the thing'))
        self.assertEqual(self.fm('do-the-thing')['routed_to'], [NOTES_ENTRY, {'target': 'inbox', 'adapter': 'record'}])

    def test_a_thought_no_rule_sends_to_the_adapter_never_reaches_it(self):
        self.route_actions_to('record')
        self.day(D1)
        self.dispatch([note('x', ['idea'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.delivered(), [])
        self.assertEqual(self.fm('t')['routed_to'], [NOTES_ENTRY])

    def test_report_audit_shape(self):
        self.route_actions_to('record')
        self.day(D1)
        report = self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(report['routed'], [{'id': 't', 'targets': [NOTES_ENTRY, {'target': 'inbox', 'adapter': 'record'}],
                                             'labels': ['todo'], 'source': f'journal/{D1}', 'body_md5': _ingest_keys.body_md5('x')}])
        self.assertEqual(json.loads((self.run_dir / 'report.json').read_text())['routed'], report['routed'])

    def test_notes_is_delivered_first_even_if_the_rules_list_another_target_first(self):
        self.save_routing({'targets': {'inbox': {'adapter': 'record', 'params': {'log': str(self.log)}}, 'notes': {'adapter': 'notes'}},
                           'rules': [{'match': [ACTION], 'to': ['inbox']}, {'match': ['*'], 'to': ['notes']}]})
        self.day(D1)
        self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.delivered()[0]['thought']['id'], 't')

    def unusable(self, routing_text, needle):
        self.day(D1)
        (self.vault / '_machine' / 'routing.yml').write_text(routing_text)
        r = self.run_dispatch([note('x', title='t')], [f'journal/{D1}.md'])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(needle, r.stderr)
        self.assertIn('nothing written', r.stderr)
        self.assertEqual(self.notes(), [])
        self.assertFalse(self.marked(D1))
        r = self.script('dispatch-targets', 'route', self.vault, self.manifest([note('x', title='t')]))
        self.assertNotEqual(r.returncode, 0)

    def test_an_undeclared_target_fails_before_anything_is_written(self):
        self.unusable(yaml.safe_dump({'targets': {'notes': {'adapter': 'notes'}}, 'rules': [{'match': ['*'], 'to': ['notes', 'mystery']}]}), 'mystery')

    def test_a_missing_adapter_fails_before_anything_is_written(self):
        self.unusable(yaml.safe_dump({'targets': {'notes': {'adapter': 'notes'}, 'away': {'adapter': 'nowhere'}},
                                      'rules': [{'match': ['*'], 'to': ['notes']}]}), 'nowhere')

    def test_an_adapter_name_is_never_a_path(self):
        self.unusable(yaml.safe_dump({'targets': {'notes': {'adapter': '../../../bin/sh'}}, 'rules': [{'match': ['*'], 'to': ['notes']}]}), 'schema')

    def test_an_absent_or_broken_routing_file_fails_before_anything_is_written(self):
        self.unusable('rules: [\n', 'does not parse')
        (self.vault / '_machine' / 'routing.yml').unlink()
        r = self.run_dispatch([note('x', title='t')], [f'journal/{D1}.md'])
        self.assertIn('no routing file', r.stderr)
        self.assertEqual(self.notes(), [])

    def test_two_notes_targets_are_refused(self):
        self.unusable(yaml.safe_dump({'targets': {'notes': {'adapter': 'notes'}, 'copy': {'adapter': 'notes'}},
                                      'rules': [{'match': ['*'], 'to': ['notes']}]}), 'only one target')

    def test_gate_route_shows_targets_and_writes_nothing(self):
        self.route_actions_to('record')
        r = self.script('dispatch-targets', 'route', self.vault, self.manifest([note('x', ['todo', 'workspace:values'], title='t')]))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)[0]
        self.assertEqual(out['targets'], [NOTES_ENTRY, {'target': 'inbox', 'adapter': 'record'}])
        self.assertFalse(out['already_filed'])
        self.assertEqual(self.notes(), [])
        self.assertEqual(self.delivered(), [])

    def test_no_target_label_or_library_is_named_in_the_dispatcher_code(self):
        text = (REAL_SCRIPTS / 'dispatch-targets').read_text()
        code = text[text.index('import argparse'):]
        for word in ('backlog', 'todo', 'workspace:', 'project:', 'AGENT_LIB', "'inbox'"):
            self.assertNotIn(word, code, word)

    def test_no_script_reads_an_external_library(self):
        for p in list(REAL_SCRIPTS.iterdir()) + list((REAL_SCRIPTS / 'adapters').iterdir()) + list((PLUGIN / 'scripts').iterdir()):
            if p.is_file():
                self.assertNotIn('AGENT_LIB', p.read_text(), p.name)


class Adapters(Base):
    """The seam: what an adapter's answer does to the thought, its unit, and the run."""

    def held_by(self, adapter, needle, **params):
        self.route_actions_to(adapter, **params)
        self.day(D1)
        self.day(D2)
        report = self.dispatch([note('x', title='a', day=D1), note('y', ['todo'], title='b', day=D2)],
                               [f'journal/{D1}.md', f'journal/{D2}.md'])
        self.assertEqual(report['marked'], [f'journal/{D1}.md'])
        [held] = report['held']
        self.assertEqual(held['day_file'], f'journal/{D2}.md')
        failure = held['failed'][0]
        self.assertEqual(failure['target'], {'target': 'inbox', 'adapter': adapter})
        self.assertEqual(failure['id'], 'b')
        self.assertIn(needle, failure['reason'])
        self.assertTrue(self.marked(D1))
        self.assertFalse(self.marked(D2))
        self.assertTrue((self.vault / 'notes' / 'b.md').exists())  # the vault copy landed; only routed_to says so
        self.assertEqual(self.fm('b')['routed_to'], [NOTES_ENTRY])
        return report

    def test_a_failed_target_holds_its_day_file(self):
        self.held_by('fail', 'not today', reason='not today')

    def test_a_crashing_adapter_is_a_failed_target(self):
        self.held_by('crash', 'crashed')

    def test_an_adapter_without_a_status_is_a_failed_target(self):
        self.held_by('garbage', 'no status')

    def test_an_adapter_abort_stops_the_run_before_any_marker(self):
        self.route_actions_to('aborts')
        self.day(D1)
        r = self.run_dispatch([note('y', ['todo'], title='b')], [f'journal/{D1}.md'])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('fake iron-rule refusal', r.stderr)
        self.assertFalse(self.marked(D1))
        self.assertFalse((self.run_dir / 'report.json').exists())

    def test_a_held_unit_commits_with_the_rest_and_commit_run_exits_non_zero(self):
        self.held_by('fail', 'refused')
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f'journal/{D2}.md', r.stderr)
        log = subprocess.run(['jj', 'log', '--no-graph', '-r', '@-', '-T', 'description'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('ingest(silent)', log)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('notes/b.md', shown)
        self.assertIn(f'journal/{D1}.md', shown)

    def test_the_held_day_clears_once_the_target_delivers(self):
        self.route_actions_to('fail')
        self.day(D1)
        n = [note('x', ['todo'], title='t')]
        self.assertTrue(self.dispatch(n, [f'journal/{D1}.md'])['held'])
        self.route_actions_to('record')
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(report['held'], [])
        self.assertEqual(report['skipped'], ['notes/t.md'])
        self.assertEqual(self.delivered()[0]['thought']['id'], 't')
        self.assertTrue(self.marked(D1))
        self.assertEqual(self.fm('t')['routed_to'], [NOTES_ENTRY, {'target': 'inbox', 'adapter': 'record'}])


class Invariant1(Base):
    def test_every_day_file_is_marked_or_held_exactly_once(self):
        self.route_actions_to('fail')
        self.day(D1)
        self.day(D2)
        report = self.dispatch([note('x', title='a', day=D1), note('y', ['todo'], title='b', day=D2)],
                               [f'journal/{D1}.md', f'journal/{D2}.md'])
        self.assertEqual(report['marked'], [f'journal/{D1}.md'])
        self.assertEqual([h['day_file'] for h in report['held']], [f'journal/{D2}.md'])

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

    def test_commit_rollback_leaves_files_unmarked_and_unheld(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        (self.run_dir / 'report.json').write_text(json.dumps(dict(json.loads((self.run_dir / 'report.json').read_text()), written=['notes/absent.md'])))
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.marked(D1))

    def test_one_run_one_commit_and_a_no_op_run_stays_quiet(self):
        self.day(D1)
        self.dispatch([note('x', title='a'), note('y', title='b')], [f'journal/{D1}.md'])
        before = subprocess.run(['jj', 'log', '--no-graph', '-r', '::@', '-T', 'commit_id ++ "\\n"'], cwd=self.vault, capture_output=True, text=True).stdout.split()
        self.assertEqual(self.commit().returncode, 0)
        after = subprocess.run(['jj', 'log', '--no-graph', '-r', '::@', '-T', 'commit_id ++ "\\n"'], cwd=self.vault, capture_output=True, text=True).stdout.split()
        self.assertEqual(len(after), len(before) + 1)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        for path in ('notes/a.md', 'notes/b.md', f'journal/{D1}.md', f'{self.run_id}/report.json'):
            self.assertIn(path, shown)
        self.run_id = '2026-11-02-2'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()
        self.dispatch([], [])
        r = self.commit()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('no-op', r.stdout)


class Invariant2(Base):
    def test_the_open_day_is_routed_but_never_marked_or_held(self):
        self.route_actions_to('record')
        self.day(TODAY)
        report = self.dispatch([note('x', ['todo'], title='a', day=TODAY)], [f'journal/{TODAY}.md'], mode='interactive')
        self.assertEqual(self.delivered()[0]['thought']['id'], 'a')
        self.assertEqual(report['marked'], [])
        self.assertFalse(self.marked(TODAY))
        self.assertEqual(report['held'], [])


class Invariant3(Base):
    """Markers land only after every write they cover has been verified."""

    def test_no_marker_when_the_vault_copy_cannot_be_written(self):
        self.day(D1)
        (self.vault / 'notes').chmod(0o555)
        self.addCleanup((self.vault / 'notes').chmod, 0o755)
        report = self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertEqual(report['marked'], [])
        self.assertEqual(report['held'][0]['failed'][0]['target'], NOTES_ENTRY)
        self.assertFalse(self.marked(D1))

    def test_markers_come_after_routed_to(self):
        self.day(D1)
        self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertTrue(self.marked(D1))
        self.assertEqual(self.fm('a')['routed_to'], [NOTES_ENTRY])


class Invariant4(Base):
    def test_open_day_failures_are_still_reported_against_the_thought(self):
        self.route_actions_to('fail')
        self.day(TODAY)
        report = self.dispatch([note('x', ['todo'], title='a', day=TODAY)], [], mode='interactive')
        self.assertEqual(report['held'], [])
        self.assertEqual(len(report['open_day_failed']), 1)
        self.assertEqual(report['open_day_failed'][0]['ref'], _ingest_keys.thought_ref(f'journal/{TODAY}', 'x'))
        self.assertIn('refused', report['open_day_failed'][0]['reason'])

    def test_an_unparseable_existing_note_fails_only_its_own_thought(self):
        self.route_actions_to('record')
        self.day(D1)
        body = 'existing'
        (self.vault / 'notes' / 'bad.md').write_text(f'---\ntitle: "un"terminated"\nsource: journal/{D1}\n---\n\n{body}\n')
        report = self.dispatch([note(body, ['todo'], title='bad-one'), note('fine', title='fine')], [f'journal/{D1}.md'])
        self.assertIn('notes/fine.md', report['written'])
        self.assertEqual(self.delivered(), [])
        self.assertEqual(len(report['held'][0]['failed']), 1)
        self.assertEqual(report['held'][0]['failed'][0]['target'], NOTES_ENTRY)

    def test_a_note_with_no_matching_rule_is_not_dropped(self):
        self.day(D1)
        self.save_routing({'targets': {'notes': {'adapter': 'notes'}}, 'rules': []})
        report = self.dispatch([note('x', title='a')], [f'journal/{D1}.md'])
        self.assertIn('no routing rule', report['held'][0]['failed'][0]['reason'])
        self.assertEqual(self.notes(), [])

    def test_no_notes_target_means_no_id_source(self):
        self.day(D1)
        self.save_routing({'targets': {'notes': {'adapter': 'notes'}, 'inbox': {'adapter': 'record', 'params': {'log': str(self.log)}}},
                           'rules': [{'match': [ACTION], 'to': ['inbox']}]})
        report = self.dispatch([note('x', ['todo'], title='a')], [f'journal/{D1}.md'])
        self.assertIn('no id source', report['held'][0]['failed'][0]['reason'])
        self.assertEqual(self.delivered(), [])


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

    def test_a_gate_edit_changes_stored_labels_frontmatter_only(self):
        self.filed()
        before = self.body('t')
        report = self.dispatch([note('x', ['todo', 'workspace:gaming'], title='t')], [], mode='interactive')
        self.assertEqual(self.fm('t')['labels'], ['todo', 'workspace:gaming'])
        self.assertEqual(self.body('t'), before)
        self.assertIn('notes/t.md', report['rewritten'])

    def test_gate_route_proposes_the_stored_labels(self):
        self.filed()
        r = self.script('dispatch-targets', 'route', self.vault, self.manifest([note('x', ['idea'], title='t')]))
        out = json.loads(r.stdout)[0]
        self.assertEqual(out['labels'], ['todo', 'workspace:values'])
        self.assertTrue(out['already_filed'])


class ReRuns(Base):
    def test_a_retry_is_safe(self):
        self.route_actions_to('record')
        self.day(D1)
        n = [note('x', ['todo'], title='t')]
        self.dispatch(n, [f'journal/{D1}.md'])
        body = (self.vault / 'notes' / 't.md').read_text()
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual((self.vault / 'notes' / 't.md').read_text(), body)
        self.assertEqual(report['skipped'], ['notes/t.md'])
        self.assertEqual(report['written'], [])
        self.assertEqual(report['rewritten'], [])
        self.assertEqual(len(self.fm('t')['routed_to']), 2)
        self.assertEqual([d['thought']['id'] for d in self.delivered()], ['t', 't'])  # idempotency on id is the adapter's

    def test_routed_to_is_unioned_and_never_removed(self):
        self.route_actions_to('record')
        self.day(D1)
        self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.route_actions_to('fail')
        report = self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(self.fm('t')['routed_to'], [NOTES_ENTRY, {'target': 'inbox', 'adapter': 'record'}])
        self.assertEqual(len(report['held']), 1)

    def test_an_older_routed_to_entry_for_the_vault_copy_is_not_repeated(self):
        self.day(D1)
        legacy = [{'container': 'vault', 'artifact': 'notes', 'name': 'vault'},
                  {'container': 'workspace', 'artifact': 'backlog', 'name': 'values'}]
        (self.vault / 'notes' / 't.md').write_text(
            f'---\ntitle: T\nlabels: [todo]\nsource: journal/{D1}\nrouted_to: {json.dumps(legacy)}\n---\n\nx\n')
        report = self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        self.assertEqual(report['skipped'], ['notes/t.md'])
        self.assertEqual(report['rewritten'], [])
        self.assertEqual(self.fm('t')['routed_to'], legacy)

    def test_outcome_skips_other_targets_and_is_neither_success_nor_failure(self):
        self.day(D1)
        n = [note('x', ['todo'], title='t')]
        self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(self.script('note-outcome', self.vault, 't', 'done', '--resolved', '2026-02-01').returncode, 0)
        self.route_actions_to('fail')
        report = self.dispatch(n, [f'journal/{D1}.md'])
        self.assertEqual(report['held'], [])
        self.assertEqual(report['routed'][0]['targets'], [NOTES_ENTRY])


class OddNotes(Base):
    def filed(self, frontmatter):
        (self.vault / 'notes' / 'odd.md').write_text(f'---\ntitle: T\nsource: journal/{D1}\n{frontmatter}---\n\nodd body\n')

    def only_its_own_thought_fails(self, report):
        self.assertIn('notes/fine.md', report['written'])
        self.assertEqual(len(report['held'][0]['failed']), 1)

    def test_malformed_routed_to_fails_only_its_own_thought(self):
        self.day(D1)
        for shape in ('routed_to:\n- foo\n', 'routed_to: nope\n', 'routed_to:\n- {container: x}\n', 'routed_to:\n- {target: x}\n'):
            with self.subTest(shape):
                self.filed(shape + 'labels: [todo]\n')
                report = self.dispatch([note('odd body', ['todo'], title='o'), note('fine', title='fine')], [f'journal/{D1}.md'])
                self.assertEqual(report['held'][0]['day_file'], f'journal/{D1}.md')
                self.assertIn('malformed', report['held'][0]['failed'][0]['reason'])
                (self.vault / 'notes' / 'fine.md').unlink()

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
        self.assertEqual(self.notes(), ['t.md'])

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
        self.route_actions_to('fail')

    def run_sources(self, source_a_labels):
        moves = [{'from': str(d / 'in.md'), 'date': '2026-07-05'} for d in (self.a, self.b)]
        notes = [dict(note('from a', source_a_labels, title='a'), source=f'r {self.a} @1'),
                 dict(note('from b', title='b'), source=f'r {self.b} @1')]
        r = self.script('dispatch-targets', 'run', self.vault, self.manifest(notes, archive_moves=moves), '--mode', 'silent', '--no-journal')
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_one_failed_source_never_blocks_another(self):
        report = self.run_sources(['todo'])
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

    def test_held_units_are_listed_with_their_target_and_reason_until_cleared(self):
        self.route_actions_to('fail', reason='inbox is closed')
        self.day(D1)
        self.dispatch([note('x', ['todo'], title='t')], [f'journal/{D1}.md'])
        out = self.status()
        self.assertIn('held: 1', out)
        self.assertIn(f'journal/{D1}.md', out)
        self.assertIn('inbox/fail: inbox is closed', out)

    def actionable(self, slug, extra='', labels='[todo]'):
        (self.vault / 'notes' / f'{slug}.md').write_text(f'---\ntitle: O\nlabels: {labels}\nsource: journal/2020-01-01\n{extra}---\n\nb\n')

    def test_undelivered_actionables_are_counted_and_listed(self):
        self.assertIn('undelivered actionables: 0\n', self.status())
        self.actionable('open-todo')
        self.actionable('open-seed', labels='[idea, session-seed]')
        self.actionable('open-delegated', labels='[delegated]', extra=f'routed_to: [{json.dumps(NOTES_ENTRY)}]\n')
        self.actionable('done', extra='outcome: done\n')
        self.actionable('handled', extra='handled: [x]\n')
        self.actionable('not-action', labels='[idea]')
        self.actionable('legacy-backlog', extra='routed_to: [{container: workspace, artifact: backlog, name: values}]\n')
        self.actionable('delivered', extra='routed_to: [{target: inbox, adapter: record}]\n')
        out = self.status()
        self.assertIn('undelivered actionables: 3 ', out)
        listed = out[out.index('undelivered actionables'):].splitlines()[1:4]
        self.assertEqual(sorted(x.strip() for x in listed), ['open-delegated', 'open-seed', 'open-todo'])

    def test_needs_label_is_counted(self):
        self.actionable('p', labels='[needs-label]')
        self.actionable('q', labels='[idea, needs-label]')
        self.actionable('r', labels='[idea]')
        out = self.status()
        self.assertIn('needs-label: 2 (0 evidence for an open proposal, 2 tied to none)', out)
        self.assertIn('open proposals: 0 (explicit 0, implicit 0; 0 with two or more evidence records)', out)

    def test_open_proposals_and_their_evidence_notes_are_counted(self):
        e = lambda q, note=None: dict({'source': 'journal/2026-01-01', 'quote': q, 'added': '2026-01-01'}, **({'note': note} if note else {}))
        (self.vault / '_machine' / 'label-proposals.yml').write_text(yaml.safe_dump({'proposals': {
            'a': {'when_to_apply': 'x', 'origin': 'explicit', 'opened': '2026-01-01', 'evidence': [e('one', 'p')]},
            'b': {'when_to_apply': 'x', 'origin': 'implicit', 'opened': '2026-01-01', 'evidence': [e('one'), e('two')]},
            'c': {'when_to_apply': 'x', 'origin': 'implicit', 'opened': '2026-01-01', 'evidence': [e('one')]}}, 'rejected': []}))
        self.actionable('p', labels='[idea, needs-label]')
        self.actionable('q', labels='[needs-label]')
        out = self.status()
        self.assertIn('needs-label: 2 (1 evidence for an open proposal, 1 tied to none)', out)
        self.assertIn('open proposals: 3 (explicit 1, implicit 2; 1 with two or more evidence records)', out)
        (self.vault / '_machine' / 'label-proposals.yml').write_text('proposals: [\n')
        self.assertIn('proposals not read', self.status())

    def test_unparseable_note_is_an_anomaly_not_a_crash(self):
        (self.vault / 'notes' / 'bad.md').write_text('---\ntitle: "un"terminated"\n---\n\nb\n')
        self.assertIn('unparseable notes: 1', self.status())

    def registry(self, sources):
        (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': sources}))

    def test_loop_guard_is_derived_from_the_vaults_rules(self):
        self.save_routing({'targets': {'notes': {'adapter': 'notes'}, 'inbox': {'adapter': 'record'}},
                           'rules': [{'match': ['*'], 'to': ['notes']}, {'match': [ACTION, 'workspace:*'], 'to': ['inbox']}]})
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['todo', 'idea']},
                       {'path': '/tmp/y', 'track': 'destructive', 'lens': ['workspace:values']}])
        out = self.status()
        self.assertIn('lens label todo is outbound', out)
        self.assertIn('lens label workspace:values is outbound', out)
        self.assertNotIn('lens label idea', out)

    def test_the_notes_only_routing_makes_nothing_outbound(self):
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['todo']}])
        self.assertNotIn('outbound', self.status())

    def test_a_none_term_makes_nothing_outbound(self):
        self.save_routing({'targets': {'notes': {'adapter': 'notes'}, 'inbox': {'adapter': 'record'}},
                           'rules': [{'match': [{'none': ['x']}], 'to': ['inbox']}]})
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['x']}])
        self.assertNotIn('outbound', self.status())

    def test_a_lens_that_is_not_a_list_is_reported_not_missed(self):
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': 'todo'}])
        self.assertIn('not a list of labels', self.status())
        self.registry([{'path': '/tmp/x', 'track': 'destructive', 'lens': ['idea', 5]}])
        self.assertIn('not a list of labels', self.status())

    def test_malformed_registry_entries_are_reported_not_crashes(self):
        for sources in (['foo'], [{'track': 'destructive'}], [{'path': '/tmp/x'}], 'x'):
            (self.vault / '_machine' / 'ingest_paths.yml').write_text(yaml.safe_dump({'sources': sources}))
            self.assertIn('malformed registry', self.status())

    def test_absent_or_broken_rules_are_stated_not_silently_clean(self):
        (self.vault / '_machine' / 'routing.yml').unlink()
        self.assertIn('loop guard not checked: no routing file', self.status())
        (self.vault / '_machine' / 'routing.yml').write_text('rules: [\n')
        self.assertIn('loop guard not checked', self.status())

    def test_no_backlog_reconciliation_remains(self):
        out = self.status()
        for gone in ('backlog', 'orphaned', 'reconciliation skipped', 'AGENT_LIB'):
            self.assertNotIn(gone, out)


class Proposals(Base):
    """Label requests in a run: evidence written by label-proposals apply, committed by the run's one commit."""

    REQUEST = {'op': 'open', 'name': 'roadmap', 'origin': 'explicit', 'when_to_apply': 'Plans and sequencing.',
               'quote': 'label:: roadmap'}
    BODY = 'Sketch the bed layout.\nlabel:: roadmap\n'

    def proposals(self):
        return yaml.safe_load((self.vault / '_machine' / 'label-proposals.yml').read_text())

    def requested(self, labels=('idea', 'needs-label'), requests=None, day=D1, **kw):
        self.day(day)
        return self.dispatch([note(self.BODY, list(labels), title='modes', day=day,
                                   label_proposals=requests if requests is not None else [self.REQUEST])],
                             [f'journal/{day}.md'], **kw)

    def test_an_explicit_request_opens_a_proposal_with_the_note_as_evidence(self):
        report = self.requested()
        self.assertEqual(report['held'], [])
        self.assertEqual([(r['name'], r['result']) for r in report['proposals']], [('roadmap', 'opened')])
        self.assertIs(report['proposal_bank'], True)
        p = self.proposals()['proposals']['roadmap']
        self.assertEqual((p['origin'], p['when_to_apply']), ('explicit', 'Plans and sequencing.'))
        self.assertEqual(p['evidence'], [{'source': f'journal/{D1}', 'quote': 'label:: roadmap', 'note': 'modes', 'added': TODAY}])
        self.assertEqual(self.fm('modes')['labels'], ['idea', 'needs-label'])  # the proposed name is not on the note
        self.assertIn('label:: roadmap', self.body('modes'))  # the request line stays: bodies are verbatim
        self.assertTrue(self.marked(D1))

    def test_one_run_one_commit_carries_the_proposal_bank(self):
        subprocess.run(['jj', 'commit', '-m', 'init'], cwd=self.vault, capture_output=True, check=True)
        self.requested()
        self.assertEqual(self.commit().returncode, 0)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        for path in ('_machine/label-proposals.yml', 'notes/modes.md', f'journal/{D1}.md'):
            self.assertIn(path, shown)
        st = subprocess.run(['jj', 'diff', '--name-only'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertNotIn('label-proposals.yml', st)

    def test_a_run_without_requests_leaves_the_proposal_bank_alone(self):
        subprocess.run(['jj', 'commit', '-m', 'init'], cwd=self.vault, capture_output=True, check=True)
        report = self.requested(requests=[])
        self.assertEqual((report['proposals'], report['proposal_bank']), ([], False))
        self.assertEqual(self.commit().returncode, 0)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertNotIn('label-proposals.yml', shown)

    def test_a_killed_run_is_recovered_with_its_proposal_bank(self):
        subprocess.run(['jj', 'commit', '-m', 'init'], cwd=self.vault, capture_output=True, check=True)
        self.requested()
        killed = self.run_id
        self.run_id = '2026-11-02-2'
        self.run_dir = self.vault / '_machine' / 'logs' / 'ingest' / self.run_id
        self.run_dir.mkdir()
        r = self.script('commit-run', '--recover', self.vault)
        self.assertEqual(json.loads(r.stdout)['recovered'], killed)
        shown = subprocess.run(['jj', 'show', '--summary', '-r', '@-'], cwd=self.vault, capture_output=True, text=True).stdout
        self.assertIn('_machine/label-proposals.yml', shown)

    def test_a_retry_adds_no_second_evidence_record(self):
        self.requested()
        report = self.requested()
        self.assertEqual([r['result'] for r in report['proposals']], ['unchanged'])
        self.assertEqual(len(self.proposals()['proposals']['roadmap']['evidence']), 1)

    def test_a_request_for_an_open_proposal_attaches(self):
        self.requested()
        self.day(D2)
        report = self.dispatch([note('More on the roadmap.\nlabel:: roadmap', ['needs-label'], title='more', day=D2,
                                     label_proposals=[dict(self.REQUEST, quote='label:: roadmap')])], [f'journal/{D2}.md'])
        self.assertEqual([r['result'] for r in report['proposals']], ['attached'])
        self.assertEqual([e['note'] for e in self.proposals()['proposals']['roadmap']['evidence']], ['modes', 'more'])

    def test_a_proposed_name_on_a_note_is_refused_and_holds_the_day(self):
        report = self.requested(labels=('idea', 'roadmap'))
        self.assertEqual(self.notes(), [])
        failure = report['held'][0]['failed'][0]
        self.assertEqual(failure['target'], NOTES_ENTRY)
        self.assertIn('not active in the bank: roadmap', failure['reason'])
        self.assertFalse(self.marked(D1))
        self.assertEqual(self.proposals()['proposals'], {})

    def test_a_retired_label_is_never_written_to_a_new_note(self):
        bank_path = self.vault / '_machine' / 'labels.yml'
        bank = yaml.safe_load(bank_path.read_text())
        bank['labels']['old'] = {'when_to_apply': 'x', 'status': 'retired'}
        bank_path.write_text(yaml.safe_dump(bank, sort_keys=False))
        report = self.requested(labels=('old',), requests=[])
        self.assertIn('not active in the bank: old', report['held'][0]['failed'][0]['reason'])

    def test_a_quote_not_verbatim_from_the_body_holds_the_day_but_files_the_note(self):
        report = self.requested(requests=[dict(self.REQUEST, quote='label:: roadmaps')])
        self.assertEqual(self.notes(), ['modes.md'])
        failure = report['held'][0]['failed'][0]
        self.assertEqual(failure['target'], {'target': 'label-proposals'})
        self.assertIn('not verbatim', failure['reason'])
        self.assertFalse(self.marked(D1))

    def test_ingest_never_accepts(self):
        report = self.requested(requests=[dict(self.REQUEST, op='accept')])
        self.assertIn('only open or attach', report['held'][0]['failed'][0]['reason'])
        self.assertNotIn('roadmap', yaml.safe_load((self.vault / '_machine' / 'labels.yml').read_text())['labels'])
        self.assertEqual(self.proposals()['proposals'], {})

    def test_a_request_for_an_active_label_is_reported_not_opened(self):
        subprocess.run(['jj', 'commit', '-m', 'init'], cwd=self.vault, capture_output=True, check=True)
        report = self.requested(labels=('idea', 'todo'), requests=[dict(self.REQUEST, name='todo')])
        self.assertEqual(report['held'], [])
        self.assertEqual(report['proposals'][0]['result'], 'skipped')
        self.assertIs(report['proposal_bank'], False)

    def test_an_unreadable_proposal_bank_holds_the_requesting_thought_only(self):
        (self.vault / '_machine' / 'label-proposals.yml').write_text('proposals: [\n')
        self.day(D1)
        self.day(D2)
        report = self.dispatch([note(self.BODY, ['needs-label'], title='modes', label_proposals=[self.REQUEST]),
                                note('plain', title='plain', day=D2)], [f'journal/{D1}.md', f'journal/{D2}.md'])
        self.assertEqual([h['day_file'] for h in report['held']], [f'journal/{D1}.md'])
        self.assertIn('does not parse', report['held'][0]['failed'][0]['reason'])
        self.assertEqual(report['marked'], [f'journal/{D2}.md'])

    def test_gate_route_shows_labels_not_in_the_bank(self):
        r = self.script('dispatch-targets', 'route', self.vault, self.manifest([note('x', ['idea', 'roadmap'], title='t')]))
        self.assertEqual(json.loads(r.stdout)[0]['inactive'], ['roadmap'])


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
        self.route_actions_to('fail')
        self.day(D1)
        self.dispatch([note('y', ['todo'], title='b')], [f'journal/{D1}.md'])
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

    def hung(self, labels, **env):
        self.day(D1)
        start = time.monotonic()
        r = subprocess.run([str(self.scripts / 'dispatch-targets'), 'run', str(self.vault),
                            str(self.manifest([note('y', labels, title='b')], [f'journal/{D1}.md'])), '--mode', 'silent'],
                           capture_output=True, text=True, env=self.env(**env), timeout=30)
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(r.returncode, 0, r.stderr)
        held = json.loads(r.stdout)['held']
        self.assertEqual([h['day_file'] for h in held], [f'journal/{D1}.md'])
        self.assertIn('timed out', held[0]['failed'][0]['reason'])
        self.assertFalse(self.marked(D1))

    def test_a_hung_notes_adapter_holds_its_unit_instead_of_aborting(self):
        self.adapter('notes', HANG)
        self.hung(['idea'], VAULT_INGEST_CALL_TIMEOUT='1')

    def test_a_hung_adapter_is_a_failed_target_and_its_unit_is_held(self):
        self.route_actions_to('hang')
        self.hung(['todo'], VAULT_INGEST_CALL_TIMEOUT='1')

    def test_the_run_deadline_bounds_the_calls_sum_and_holds_the_unit(self):
        # F1: a caller with its own timeout (claude's Bash tool) can bound the whole command, not one call.
        self.route_actions_to('hang')
        self.hung(['todo'], VAULT_INGEST_CALL_TIMEOUT='60', VAULT_INGEST_RUN_DEADLINE='2')

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

    def test_sigterm_kills_the_running_adapter_group(self):
        # F1: adapters run in their own sessions; killing dispatch-targets must not leave one running.
        pids = self.tmp / 'adapter-pids'
        self.adapter('hang', f'#!/bin/sh\necho $$ >>{pids}\nsleep 60 &\necho $! >>{pids}\nsleep 60\n')
        self.route_actions_to('hang')
        self.day(D1)
        proc = subprocess.Popen([str(self.scripts / 'dispatch-targets'), 'run', str(self.vault),
                                 str(self.manifest([note('y', ['todo'], title='b')], [f'journal/{D1}.md'])),
                                 '--mode', 'silent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env())
        for _ in range(100):
            if pids.exists() and len(pids.read_text().split()) == 2:
                break
            time.sleep(0.1)
        adapters = [int(p) for p in pids.read_text().split()]
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 128 + signal.SIGTERM)
        time.sleep(0.5)
        for pid in adapters:
            with self.assertRaises(ProcessLookupError, msg=f'adapter {pid} survived'):
                os.kill(pid, 0)


if __name__ == '__main__':
    unittest.main()
