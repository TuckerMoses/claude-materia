"""Tests for the Order step 4 one-offs. Removed with them."""
import datetime
import subprocess
import unittest

import yaml

from test_run_sequence import Base, SCRIPTS, TODAY


class Repair(Base):
    def run_it(self, *args):
        return self.script('frontmatter-repair', self.vault, *args)

    def test_repairs_an_unescaped_quote_keeping_values_and_the_body(self):
        path = self.vault / 'notes' / 'b.md'
        path.write_text('---\ntitle: "Book title: "Ghosts" to "Us""\nlabels: [idea, reading]\ncreated: 2026-01-01\nsource: journal/2026-01-01\nrelated:\n  - "[[x]]"\n---\n\nbody "kept"\n')
        before = path.read_text()
        self.assertIn('would repair', self.run_it().stdout)
        self.assertEqual(path.read_text(), before)
        self.assertEqual(self.run_it('--apply').returncode, 0)
        data = self.fm('b')
        self.assertEqual(data['title'], 'Book title: "Ghosts" to "Us"')
        self.assertEqual(data['labels'], ['idea', 'reading'])
        self.assertEqual(data['created'], datetime.date(2026, 1, 1))
        self.assertEqual(data['related'], ['[[x]]'])
        self.assertEqual(self.body('b'), '\nbody "kept"\n')

    def test_a_parseable_note_is_untouched_and_a_rerun_finds_nothing(self):
        path = self.vault / 'notes' / 'ok.md'
        path.write_text('---\ntitle: "plain"\n---\n\nb\n')
        before = path.read_text()
        out = self.run_it('--apply')
        self.assertEqual(path.read_text(), before)
        self.assertIn('0 repaired, 0 failed', out.stdout)

    def test_unrecoverable_is_reported_and_left_alone(self):
        path = self.vault / 'notes' / 'bad.md'
        path.write_text('---\n: : :\n---\n\nb\n')
        before = path.read_text()
        r = self.run_it('--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAILED', r.stdout)
        self.assertEqual(path.read_text(), before)


class LegacyRoute(Base):
    def setUp(self):
        super().setUp()
        self.gate_file = self.tmp / 'gate.yml'

    def add(self, slug, labels, extra='', body='the body\n'):
        (self.vault / 'notes' / f'{slug}.md').write_text(
            f'---\ntitle: "{slug} title"\nlabels: [{", ".join(labels)}]\ncreated: 2026-01-05\ncaptured: 2026-01-02\nsource: journal/2026-01-02\n{extra}---\n\n{body}')

    def legacy(self, *args):
        return self.script('legacy-route', self.vault, *args)

    def test_dry_run_changes_nothing(self):
        self.add('n', ['todo', 'workspace:values'])
        self.add('s', ['todo'], 'status: done\n')
        before = (self.vault / 'notes' / 'n.md').read_text()
        r = self.legacy()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('would route: n', r.stdout)
        self.assertIn('Dry run', r.stdout)
        self.assertEqual((self.vault / 'notes' / 'n.md').read_text(), before)
        self.assertEqual(self.items(), [])
        self.assertNotIn('outcome', self.fm('s'))

    def test_open_note_gets_an_item_and_routed_to_with_the_spec_mapping(self):
        self.add('n', ['todo', 'workspace:values'])
        self.assertEqual(self.legacy('--apply').returncode, 0)
        item = self.items()[0]
        self.assertEqual(item['id'], 'n')
        self.assertEqual(item['title'], 'n title')
        self.assertEqual(item['source'], 'notes/n')
        self.assertEqual(item['added'], datetime.date(2026, 1, 2))
        self.assertEqual(item['body'], 'the body')
        self.assertEqual(item['labels'], ['todo', 'workspace:values'])
        self.assertEqual(self.fm('n')['routed_to'], [
            {'container': 'vault', 'artifact': 'notes', 'name': 'vault'},
            {'container': 'workspace', 'artifact': 'backlog', 'name': 'values'}])

    def test_no_captured_falls_back_to_created(self):
        (self.vault / 'notes' / 'n.md').write_text('---\ntitle: T\nlabels: [todo]\ncreated: 2026-03-04\nsource: x\n---\n\nb\n')
        self.legacy('--apply')
        self.assertEqual(self.items('kernel')[0]['added'], datetime.date(2026, 3, 4))

    def test_knowledge_notes_are_not_selected_or_touched(self):
        self.add('k', ['idea', 'workspace:values'])
        before = (self.vault / 'notes' / 'k.md').read_text()
        self.assertIn('selected 0', self.legacy('--apply').stdout)
        self.assertEqual((self.vault / 'notes' / 'k.md').read_text(), before)

    def test_status_done_becomes_an_outcome_and_the_note_is_skipped(self):
        self.add('s', ['todo', 'workspace:values'], 'status: done\n')
        self.legacy('--apply')
        data = self.fm('s')
        self.assertEqual(data['outcome'], 'done')
        self.assertEqual(data['resolved'].isoformat(), TODAY)
        self.assertEqual(data['status'], 'done')
        self.assertNotIn('routed_to', data)
        self.assertEqual(self.items(), [])

    def test_handled_is_closed_with_no_outcome_written(self):
        self.add('h', ['todo'], 'handled: [x]\n')
        self.legacy('--apply')
        self.assertNotIn('outcome', self.fm('h'))
        self.assertNotIn('routed_to', self.fm('h'))
        self.assertEqual(self.items('kernel'), [])

    def test_gate_edits_labels_and_routes_on_them(self):
        self.add('n', ['todo', 'session-seed', 'workspace:values'])
        self.gate_file.write_text(yaml.safe_dump({'n': {'labels': ['session-seed', 'workspace:gaming']}}))
        r = self.legacy('--gate', self.gate_file, '--apply')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fm('n')['labels'], ['session-seed', 'workspace:gaming'])
        self.assertEqual(self.items('gaming')[0]['labels'], ['session-seed', 'workspace:gaming'])
        self.assertEqual(self.items('values'), [])

    def test_gate_drop_closes_the_note_on_every_rerun(self):
        self.add('n', ['todo'])
        self.gate_file.write_text(yaml.safe_dump({'n': 'drop'}))
        self.legacy('--gate', self.gate_file, '--apply')
        self.assertEqual(self.fm('n')['outcome'], 'dropped')
        self.assertEqual(self.items('kernel'), [])
        self.assertEqual(self.legacy('--apply').returncode, 0)
        self.assertEqual(self.items('kernel'), [])

    def test_gate_naming_an_absent_note_or_an_odd_value_is_refused(self):
        self.add('n', ['todo'])
        self.gate_file.write_text(yaml.safe_dump({'absent': 'drop'}))
        self.assertNotEqual(self.legacy('--gate', self.gate_file, '--apply').returncode, 0)
        self.gate_file.write_text(yaml.safe_dump({'n': 'maybe'}))
        r = self.legacy('--gate', self.gate_file, '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.items('kernel'), [])

    def test_rerun_is_idempotent(self):
        self.add('n', ['todo', 'workspace:values'])
        self.legacy('--apply')
        before = ((self.vault / 'notes' / 'n.md').read_text(), self.items())
        r = self.legacy('--apply')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(((self.vault / 'notes' / 'n.md').read_text(), self.items()), before)

    def test_bad_slug_is_reported_and_not_appended(self):
        self.add('trailing-', ['todo'])
        r = self.legacy('--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAILED: trailing-: slug', r.stdout)
        self.assertEqual(self.items('kernel'), [])
        self.assertNotIn('routed_to', self.fm('trailing-'))

    def test_unresolved_gets_no_routed_to_and_is_retried_after_the_fix(self):
        self.add('n', ['todo', 'workspace:new'])
        r = self.legacy('--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('workspace:new', r.stdout)
        self.assertNotIn('routed_to', self.fm('n'))
        d = self.tmp / 'new'
        d.mkdir()
        (d / 'BACKLOG.yml').write_text('items: []\n')
        self.rows.append({'name': 'new', 'kind': 'workspace', 'path': str(d), 'artifacts': {'backlog': 'BACKLOG.yml'}})
        self.save_lib()
        self.assertEqual(self.legacy('--apply').returncode, 0)
        self.assertEqual(self.items('new')[0]['id'], 'n')

    def test_a_failed_append_gets_no_routed_to(self):
        self.add('n', ['todo', 'workspace:values'])
        (self.tmp / 'values' / 'BACKLOG.yml').unlink()
        r = self.legacy('--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('routed_to', self.fm('n'))

    def test_a_tie_is_warned_about(self):
        self.add('n', ['todo', 'workspace:values', 'workspace:gaming'])
        self.assertIn('WARNING tie resolved', self.legacy('--apply').stdout)
        self.assertEqual(self.items('gaming')[0]['id'], 'n')

    def test_unparseable_note_is_an_anomaly_not_a_crash(self):
        (self.vault / 'notes' / 'bad.md').write_text('---\ntitle: "un"terminated"\n---\n\nb\n')
        self.add('n', ['todo'])
        r = self.legacy('--apply')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('anomaly: bad.md', r.stdout)
        self.assertEqual(self.items('kernel')[0]['id'], 'n')

    def test_after_the_pass_status_has_no_orphans(self):
        self.add('n', ['todo'])
        self.add('s', ['todo'], 'status: done\n')
        self.legacy('--apply')
        self.assertNotIn('orphaned', self.script('ingest-status', self.vault).stdout)


class Csv(Base):
    def csv(self, text):
        path = self.tmp / 'notes.csv'
        path.write_text(text)
        return path

    def convert(self, path, *extra):
        return self.script('notes-csv-to-days', self.vault, path, '--date-column', 'Date', '--body-column', 'Body', *extra)

    def test_dry_run_writes_nothing(self):
        r = self.convert(self.csv('Date,Body\n2024-01-02,hello\n'))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(list((self.vault / 'journal').iterdir()), [])

    def test_rows_join_by_date_and_formats_are_read(self):
        path = self.csv('Date,Body\n2024-01-02,one\n"Jan 2, 2024",two\n01/03/2024,"multi\nline"\n2024-01-04T10:00:00Z,four\n')
        self.assertEqual(self.convert(path, '--apply').returncode, 0)
        self.assertEqual((self.vault / 'journal' / '2024-01-02.md').read_text(), 'one\n\ntwo\n')
        self.assertEqual((self.vault / 'journal' / '2024-01-03.md').read_text(), 'multi\nline\n')
        self.assertTrue((self.vault / 'journal' / '2024-01-04.md').exists())

    def test_rerun_adds_nothing_and_existing_unmarked_text_is_kept(self):
        self.day('2024-01-02', 'already here\n')
        path = self.csv('Date,Body\n2024-01-02,new row\n')
        self.convert(path, '--apply')
        self.convert(path, '--apply')
        self.assertEqual((self.vault / 'journal' / '2024-01-02.md').read_text(), 'already here\n\nnew row\n')

    def test_a_marked_day_is_refused(self):
        self.day('2024-01-02', '---\ningested: true\n---\nold\n')
        r = self.convert(self.csv('Date,Body\n2024-01-02,new\n'), '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('new', (self.vault / 'journal' / '2024-01-02.md').read_text())

    def test_title_column_is_kept_unless_it_repeats_the_first_line(self):
        path = self.csv('Date,Title,Body\n2024-01-02,Trip,packing list\n2024-01-03,same,same\nrest\n')
        self.convert(path, '--title-column', 'Title', '--apply')
        self.assertEqual((self.vault / 'journal' / '2024-01-02.md').read_text(), 'Trip\npacking list\n')

    def test_bad_dates_today_and_missing_columns_are_reported(self):
        r = self.convert(self.csv(f'Date,Body\nsometime,a\n{TODAY},b\n'), '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('cannot read date', r.stdout)
        self.assertIn('not a closed day', r.stdout)
        self.assertEqual(list((self.vault / 'journal').iterdir()), [])
        r = self.convert(self.csv('When,Text\n2024-01-02,a\n'))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no column', r.stderr)

    def test_empty_rows_are_skipped_and_a_bom_is_handled(self):
        path = self.tmp / 'bom.csv'
        path.write_bytes('﻿Date,Body\n2024-01-02,x\n2024-01-03,\n'.encode('utf-8'))
        self.assertEqual(self.convert(path, '--apply').returncode, 0)
        self.assertFalse((self.vault / 'journal' / '2024-01-03.md').exists())


if __name__ == '__main__':
    unittest.main()
