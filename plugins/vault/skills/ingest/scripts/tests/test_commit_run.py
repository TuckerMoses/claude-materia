"""commit-run against a throwaway jj vault: exact-path commits, a landed-but-timed-out commit, and recovery of a proposal
bank an interrupted run left uncommitted.

Run from anywhere:
  python3 -m unittest discover plugins/vault/skills/ingest/scripts/tests
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT_RUN = HERE.parent / 'commit-run'
PLUGIN = HERE.parents[3]
PROPOSALS = PLUGIN / 'scripts' / 'label-proposals'
ASSETS = PLUGIN / 'skills' / 'vault' / 'assets'
ODD = ['a~b', 'c&d', 'e|f', 'g(h)', 'i j']


class Vault(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = self.tmp / 'vault'
        for d in ('journal', 'notes', '_machine/logs/ingest'):
            (self.vault / d).mkdir(parents=True)
        subprocess.run(['jj', 'git', 'init', str(self.vault)], capture_output=True, check=True)
        for key, value in (('user.name', 'test'), ('user.email', 'test@test.invalid')):
            subprocess.run(['jj', 'config', 'set', '--repo', key, value], cwd=self.vault, capture_output=True, check=True)
        self.env = dict(os.environ)

    def jj(self, *args):
        return subprocess.run(['jj', '--no-pager', *args], cwd=self.vault, capture_output=True, text=True,
                              check=True).stdout

    def commit_all(self, message='init'):
        self.jj('commit', '-m', message)

    def dirty(self):
        return self.jj('diff', '--name-only', '-r', '@').splitlines()

    def files(self, rev='@-'):
        return sorted(self.jj('diff', '--name-only', '-r', rev).splitlines())

    def commit_run(self, *args):
        return subprocess.run([str(COMMIT_RUN), *map(str, args)], capture_output=True, text=True, env=self.env)

    def run_fixture(self, run, slugs, report_extra=None):
        rd = self.vault / '_machine' / 'logs' / 'ingest' / run
        rd.mkdir(parents=True)
        (self.vault / 'journal' / '2026-01-02.md').write_text('---\ningested: true\n---\nday text\n')
        for slug in slugs:
            (self.vault / 'notes' / f'{slug}.md').write_text('---\ntitle: "T"\nlabels: [idea]\n---\nbody\n')
        (rd / 'run.json').write_text(json.dumps({'run': run, 'filed': len(slugs), 'day_files': 1, 'parked': 0}))
        (rd / 'proposals.json').write_text('[]\n')
        (rd / 'entry.md').write_text(f'## {run} · silent\n')
        report = dict({'written': [f'notes/{s}.md' for s in slugs], 'marked': ['journal/2026-01-02.md'],
                       'advanced': [], 'moved': [], 'skipped': []}, **(report_extra or {}))
        (rd / 'report.json').write_text(json.dumps(report))
        return rd

    def commit(self, run, rd):
        return self.commit_run(self.vault, rd / 'report.json', rd / 'entry.md', run, 'silent')

    def shim(self, script):
        """A jj on PATH that wraps the real one."""
        d = self.tmp / 'shim'
        d.mkdir()
        (d / 'jj').write_text(script.replace('REALJJ', shutil.which('jj')))
        (d / 'jj').chmod(0o755)
        self.env['PATH'] = f'{d}:{self.env["PATH"]}'


class OddNames(Vault):
    def test_every_odd_name_lands_in_the_run_commit(self):
        self.commit_all()
        rd = self.run_fixture('2026-01-03-1', ODD)
        r = self.commit(rd.name, rd)
        self.assertEqual(r.returncode, 0, r.stderr)
        committed = self.files()
        for slug in ODD:
            self.assertIn(f'notes/{slug}.md', committed)
        self.assertEqual([p for p in self.dirty() if p != 'CHANGELOG.md'], [])

    def test_recover_lands_odd_names(self):
        self.commit_all()
        rd = self.run_fixture('2026-01-03-1', ODD)
        r = self.commit_run('--recover', self.vault)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['recovered'], '2026-01-03-1')
        log = self.jj('log', '--no-graph', '-r', 'description(glob:"ingest(recovered)*")', '-T', 'commit_id')
        committed = self.files(log.strip())
        for slug in ODD:
            self.assertIn(f'notes/{slug}.md', committed)
        self.assertIn(f'_machine/logs/ingest/{rd.name}/report.json', committed)


class TimedOut(Vault):
    def test_a_commit_that_landed_then_timed_out_is_a_success(self):
        self.commit_all()
        rd = self.run_fixture('2026-01-03-1', ['t'])
        self.shim('#!/bin/sh\nfor a in "$@"; do [ "$a" = commit ] && { REALJJ "$@" >/dev/null 2>&1; '
                  'echo "jj commit timed out after 300s" >&2; exit 124; }; done\nexec REALJJ "$@"\n')
        r = self.commit(rd.name, rd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('notes/t.md', self.files())
        self.assertIn('ingested: true', (self.vault / 'journal' / '2026-01-02.md').read_text())  # not rolled back
        self.assertTrue(json.loads((rd / 'report.json').read_text())['completed'])


class OrphanProposals(Vault):
    """A run killed between `label-proposals apply` and its finish leaves the proposal bank dirty with no report.
    The next run's recover commits it, so the gate's accept is not refused."""

    def setUp(self):
        super().setUp()
        shutil.copy(ASSETS / 'labels.yml', self.vault / '_machine' / 'labels.yml')
        shutil.copy(ASSETS / 'label-proposals.yml', self.vault / '_machine' / 'label-proposals.yml')
        self.commit_all()
        requests = self.tmp / 'requests.json'
        requests.write_text(json.dumps([{'op': 'open', 'name': 'roadmap', 'origin': 'explicit', 'ref': 'r1',
                                         'source': 'journal/2026-01-02', 'quote': 'label:: roadmap', 'note': 'n',
                                         'when_to_apply': 'Plans and sequencing.'}]))
        r = subprocess.run([str(PROPOSALS), 'apply', str(self.vault), str(requests)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dirty(), ['_machine/label-proposals.yml'])  # ...and then the run was killed

    def accept(self):
        return subprocess.run([str(PROPOSALS), 'accept', str(self.vault), '--name', 'roadmap'], capture_output=True,
                              text=True)

    def test_recover_commits_the_orphaned_proposal_bank_and_accept_works(self):
        (self.vault / 'journal' / '2026-01-09.md').write_text('an open day, not ours\n')
        r = self.commit_run('--recover', self.vault)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out['recovered'], out['proposal_bank']), (None, True))
        self.assertEqual(self.files(), ['_machine/label-proposals.yml'])
        self.assertIn('ingest(recovered)', self.jj('log', '--no-graph', '-r', '@-', '-T', 'description'))
        self.assertEqual(sorted(p for p in self.dirty() if p != 'CHANGELOG.md'), ['journal/2026-01-09.md'])
        r = self.accept()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_pending_run_still_claims_its_own_proposal_bank(self):
        rd = self.run_fixture('2026-01-03-1', ['t'], {'proposal_bank': True})
        r = self.commit_run('--recover', self.vault)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['recovered'], rd.name)
        self.assertNotIn('proposal_bank', out)
        self.assertIn('_machine/label-proposals.yml', self.files())

    def test_a_broken_proposal_bank_is_not_committed(self):
        path = self.vault / '_machine' / 'label-proposals.yml'
        path.write_text('proposals: [not, a, mapping]\n')
        n = self.jj('log', '--no-graph', '-r', '::@-', '-T', 'commit_id ++ "\\n"').split()
        r = self.commit_run('--recover', self.vault)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('label-proposals.yml', r.stderr)
        self.assertEqual(self.jj('log', '--no-graph', '-r', '::@-', '-T', 'commit_id ++ "\\n"').split(), n)
        self.assertEqual(self.dirty(), ['_machine/label-proposals.yml'])


    def test_a_never_committed_proposal_bank_is_not_a_leftover(self):
        fresh = self.tmp / 'fresh'
        subprocess.run(['jj', 'git', 'init', str(fresh)], capture_output=True, check=True)
        (fresh / '_machine').mkdir()
        shutil.copy(ASSETS / 'label-proposals.yml', fresh / '_machine' / 'label-proposals.yml')
        r = self.commit_run('--recover', fresh)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'recovered': None})


if __name__ == '__main__':
    unittest.main()
