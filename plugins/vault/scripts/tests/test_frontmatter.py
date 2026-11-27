"""Label edits touch the labels line and nothing else; CRLF notes keep their line endings; an undecodable note blocks
only the operations whose label it might carry.

Run from anywhere:
  python3 -m unittest discover plugins/vault/scripts/tests
"""
import json
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_labels import Base, lb  # noqa: E402

import _note_frontmatter as fm  # noqa: E402

# Hand-written frontmatter a full re-dump would reshape or, under YAML 1.1, reinterpret.
HAND = ("---\n"
        "title: \"T\"\n"
        "labels: [roadmap, 'workspace:learning']\n"
        "related: [one-note, two-note,\n"
        "  three-note]\n"
        "links:\n"
        "  - slug: other\n"
        "    why: because\n"
        "time: 12:30\n"
        "on: yes\n"
        "created: 2026-01-02\n"
        "---\n"
        "\n"
        "Body mentions roadmap.\n")
BLOCK = ("---\n"
         "title: \"T\"\n"
         "labels:\n"
         "  - roadmap\n"
         "  - idea\n"
         "related:\n"
         "  - one-note\n"
         "created: 2026-01-02\n"
         "---\n"
         "\n"
         "Body.\n")


class Minimal(Base):
    def write(self, slug, text):
        p = self.vault / 'notes' / f'{slug}.md'
        p.write_bytes(text.encode())
        return p

    def expect(self, text, old_line, new_line):
        self.assertEqual(text.count(old_line), 1)
        return text.replace(old_line, new_line).encode()

    def test_rename_rewrites_only_the_labels_line(self):
        p = self.write('hand', HAND)
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_bytes(), self.expect(HAND, "labels: [roadmap, 'workspace:learning']",
                                                     "labels: [plans, 'workspace:learning']"))

    def test_merge_rewrites_only_the_labels_line(self):
        p = self.write('hand', HAND)
        self.init()
        r = self.bank('merge', '--from', 'roadmap', '--into', 'idea')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_bytes(), self.expect(HAND, "labels: [roadmap, 'workspace:learning']",
                                                     "labels: [idea, 'workspace:learning']"))

    def test_relabel_rewrites_only_the_labels_line(self):
        p = self.write('hand', HAND)
        self.init()
        r = self.relabel({'hand': {'remove': ['roadmap'], 'add': ['idea']}})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_bytes(), self.expect(HAND, "labels: [roadmap, 'workspace:learning']",
                                                     "labels: ['workspace:learning', idea]"))

    def test_a_block_labels_list_falls_back_to_a_full_rewrite(self):
        p = self.write('block', BLOCK)
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        text = p.read_text()
        before, after = fm.parse(BLOCK), fm.parse(text)
        self.assertEqual(after['labels'], ['plans', 'idea'])
        self.assertEqual({k: v for k, v in after.items() if k != 'labels'},
                         {k: v for k, v in before.items() if k != 'labels'})
        self.assertTrue(text.endswith('---\n\nBody.\n'))

    def test_the_fallback_refuses_to_reinterpret_a_value(self):
        for extra, key in (('time: 12:30\n', 'time'), ('on: yes\n', 'on')):
            with self.subTest(key=key):
                text = BLOCK.replace('created:', extra + 'created:')
                p = self.write('block', text)
                self.init()
                before = self.state()
                r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
                self.assert_refused(r, 'block', *before)
                self.assertIn(key, r.stderr)
                self.assertEqual(p.read_bytes(), text.encode())

    def test_a_quoted_label_is_found_and_renamed(self):
        p = self.write('quoted', HAND.replace("[roadmap, 'workspace:learning']", "['roadmap', \"idea\"]"))
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(fm.parse(p.read_text())['labels'], ['plans', 'idea'])
        self.assertIn('related: [one-note, two-note,\n  three-note]\n', p.read_text())


class Crlf(Base):
    TEXT = HAND.replace('\n', '\r\n')

    def test_a_crlf_note_is_read(self):
        self.assertEqual(fm.parse(self.TEXT)['labels'], ['roadmap', 'workspace:learning'])
        self.assertEqual(fm.body_of(self.TEXT), 'Body mentions roadmap.\r\n')

    def test_rename_keeps_every_crlf(self):
        p = self.vault / 'notes' / 'crlf.md'
        p.write_bytes(self.TEXT.encode())
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['notes'], ['crlf'])
        self.assertEqual(p.read_bytes(), self.TEXT.replace('[roadmap,', '[plans,').encode())

    def test_the_fallback_writes_crlf_too(self):
        text = BLOCK.replace('\n', '\r\n')
        p = self.vault / 'notes' / 'crlf.md'
        p.write_bytes(text.encode())
        self.init()
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = p.read_bytes()
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        self.assertTrue(raw.endswith(b'---\r\n\r\nBody.\r\n'))
        self.assertEqual(fm.parse(raw.decode())['labels'], ['plans', 'idea'])


class Undecodable(Base):
    def setUp(self):
        super().setUp()
        self.note('a', ['roadmap'])
        (self.vault / 'notes' / 'latin1.md').write_bytes('---\nlabels: [idea]\n---\ncafé\n'.encode('latin-1'))
        self.init()

    def test_an_unrelated_undecodable_note_blocks_nothing(self):
        r = self.bank('show', '--name', 'roadmap')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['notes'], ['a'])
        r = self.bank('rename', '--from', 'roadmap', '--to', 'plans')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.bank('merge', '--from', 'plans', '--into', 'idea')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bank('remove', '--name', 'old-thing').returncode, 0)

    def test_an_undecodable_note_naming_the_label_blocks_it(self):
        before = self.state()
        r = self.bank('rename', '--from', 'idea', '--to', 'ideas')
        self.assert_refused(r, 'latin1', *before)

    def test_the_library_says_the_same(self):
        self.assertEqual(lb.carriers(self.vault, 'roadmap'), ['a'])
        with self.assertRaises(lb.BankError):
            lb.carriers(self.vault, 'idea')


class Verify(unittest.TestCase):
    def test_relabel_checks_every_other_key(self):
        new = fm.relabel(HAND, ['plans'])
        self.assertEqual(fm.parse(new)['labels'], ['plans'])
        self.assertEqual(new, HAND.replace("[roadmap, 'workspace:learning']", '[plans]'))

    def test_relabel_keeps_a_labels_line_comment_out_of_the_minimal_path(self):
        text = HAND.replace("'workspace:learning']", "'workspace:learning']  # mine")
        new = fm.relabel(text.replace('time: 12:30\n', '').replace('on: yes\n', ''), ['plans'])
        self.assertEqual(fm.parse(new)['labels'], ['plans'])

    def test_no_frontmatter_is_refused(self):
        with self.assertRaises(fm.NoteError):
            fm.relabel('just a body\n', ['x'])


if __name__ == '__main__':
    unittest.main()
