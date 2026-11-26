"""label-proposals and the proposal bank schema, as tests. Real script against a throwaway jj vault.

Run from anywhere:
  python3 -m unittest discover plugins/vault/scripts/tests
"""
import datetime
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_labels as tl  # noqa: E402  (its Base: a jj vault with the seed bank plus tl.EXTRA)

PROPOSALS_SEED = tl.PLUGIN / 'skills' / 'vault' / 'assets' / 'label-proposals.yml'
sys.path.insert(0, str(tl.SCRIPTS))
import _label_proposals as lp  # noqa: E402

TODAY = datetime.date.today().isoformat()
E1 = {'source': 'journal/2026-11-21', 'quote': 'Sketch the bed layout.', 'note': 'sketch-the-bed-layout', 'added': '2026-11-21'}


class Base(tl.Base):
    def setUp(self):
        super().setUp()
        self.props_path = self.vault / '_machine' / 'label-proposals.yml'
        shutil.copy(PROPOSALS_SEED, self.props_path)

    def seed(self, proposals=None, rejected=None):
        data = {'proposals': proposals or {}, 'rejected': rejected or []}
        self.props_path.write_text(PROPOSALS_SEED.read_text().split('\nproposals:')[0] + '\n' + yaml.safe_dump(data, sort_keys=False))

    def props(self, *args):
        return self.run_script('label-proposals', args[0], self.vault, *args[1:])

    def data(self):
        return yaml.safe_load(self.props_path.read_text())

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def one_commit(self, before, files, subject):
        self.assertEqual(self.commits(), before + 1)
        self.assertEqual(self.last_files(), files)
        self.assertEqual(self.last_description().splitlines()[0], subject)
        self.assertEqual(self.jj('diff', '--name-only', '-r', '@'), '')


def proposal(origin='implicit', evidence=(E1,), opened='2026-11-21', text='Plans and sequencing.'):
    return {'when_to_apply': text, 'origin': origin, 'opened': opened, 'evidence': [dict(e) for e in evidence]}


class Schema(unittest.TestCase):
    def check(self, data):
        try:
            lp.validate(data)
            return True
        except lp.ProposalError:
            return False

    def test_template_and_spec_shape_validate(self):
        self.assertTrue(self.check(yaml.safe_load(PROPOSALS_SEED.read_text())))
        self.assertTrue(self.check({'proposals': {'roadmap': proposal()},
                                    'rejected': [{'name': 'nix-stuff', 'reason': 'too broad', 'date': '2026-12-03'}]}))
        self.assertTrue(self.check({'proposals': {'a': dict(proposal(), reopened={'reason': 'r', 'date': '2026-01-01'})}, 'rejected': []}))

    def test_bad_shapes(self):
        for bad in (dict(proposal(), origin='human'), dict(proposal(), opened='soon'), dict(proposal(), extra=1),
                    dict(proposal(), when_to_apply=' '), {k: v for k, v in proposal().items() if k != 'evidence'},
                    dict(proposal(), evidence=[{'source': 'x', 'quote': 'q'}]),
                    dict(proposal(), evidence=[dict(E1, note='../x')])):
            self.assertFalse(self.check({'proposals': {'a': bad}, 'rejected': []}), bad)
        self.assertFalse(self.check({'proposals': {'Bad Name': proposal()}, 'rejected': []}))
        self.assertFalse(self.check({'proposals': {}, 'rejected': [{'name': 'x', 'reason': 'r'}]}))
        self.assertFalse(self.check({'proposals': {}}))

    def test_normalise(self):
        self.assertEqual(lp.normalise('Nix Stuff'), 'nix-stuff')
        self.assertEqual(lp.normalise('Workspace:My App'), 'workspace:my-app')
        self.assertEqual(lp.normalise(' ai / Agents '), 'ai/agents')
        self.assertIsNone(lp.normalise('!!!'))


class Open(Base):
    def test_open_implicit_and_explicit_each_one_commit(self):
        self.init()
        n = self.commits()
        out = self.ok(self.props('open', '--name', 'plans', '--when-to-apply', 'Plans.'))
        self.assertEqual(out['origin'], 'implicit')
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(open): plans')
        self.assertEqual(self.data()['proposals']['plans'],
                         {'when_to_apply': 'Plans.', 'origin': 'implicit', 'opened': TODAY, 'evidence': []})
        self.ok(self.props('open', '--name', 'roadmapping', '--when-to-apply', 'R.', '--explicit',
                           '--source', 'journal/2026-11-21', '--quote', 'label:: roadmapping', '--note', 'n'))
        p = self.data()['proposals']['roadmapping']
        self.assertEqual(p['origin'], 'explicit')
        self.assertEqual(p['evidence'], [{'source': 'journal/2026-11-21', 'quote': 'label:: roadmapping', 'note': 'n', 'added': TODAY}])
        self.assertTrue(self.props_path.read_text().startswith('# Label proposals'))

    def test_refusals_change_nothing(self):
        self.seed({'plans': proposal()}, [{'name': 'nix-stuff', 'reason': 'too broad', 'date': '2026-12-03'}])
        self.init()
        before = self.state()
        self.assert_refused(self.props('open', '--name', 'plans', '--when-to-apply', 'x'), 'already an open proposal', *before)
        self.assert_refused(self.props('open', '--name', 'roadmap', '--when-to-apply', 'x'), 'apply it instead', *before)
        self.assert_refused(self.props('open', '--name', 'old-thing', '--when-to-apply', 'x'), 'never revived', *before)
        self.assert_refused(self.props('open', '--name', 'Nix Things', '--when-to-apply', 'x'), 'did you mean nix-things', *before)
        self.assert_refused(self.props('open', '--name', 'nix-stuff', '--when-to-apply', 'x'), 'too broad', *before)
        self.assert_refused(self.props('open', '--name', 'ok', '--when-to-apply', ' '), 'schema', *before)
        self.assert_refused(self.props('open', '--name', 'ok', '--when-to-apply', 'x', '--note', 'n'), 'needs --source', *before)
        self.assert_refused(self.props('open', '--name', 'ok', '--when-to-apply', 'x', '--source', 's'), 'source and quote', *before)

    def test_explicit_reopens_a_rejected_name_carrying_the_old_reason(self):
        self.seed(rejected=[{'name': 'nix-stuff', 'reason': 'too broad', 'date': '2026-12-03'}])
        self.init()
        out = self.ok(self.props('open', '--name', 'nix-stuff', '--when-to-apply', 'Nix config.', '--explicit'))
        self.assertEqual(out['reopened'], {'reason': 'too broad', 'date': '2026-12-03'})
        data = self.data()
        self.assertEqual(data['rejected'], [])
        self.assertEqual(data['proposals']['nix-stuff']['reopened'], {'reason': 'too broad', 'date': '2026-12-03'})
        self.assertIn('(reopened)', self.last_description())

    def test_refuses_uncommitted_changes_an_absent_bank_and_a_broken_one(self):
        self.init()
        self.props_path.write_text(self.props_path.read_text() + '\n')
        before = self.state()
        self.assert_refused(self.props('open', '--name', 'x', '--when-to-apply', 'x'), 'uncommitted', *before)
        self.props_path.unlink()
        before = self.state()
        self.assert_refused(self.props('open', '--name', 'x', '--when-to-apply', 'x'), 'no proposal bank', *before)
        self.props_path.write_text('proposals: {a: {origin: implicit}}\nrejected: []\n')
        before = self.state()
        self.assert_refused(self.props('open', '--name', 'x', '--when-to-apply', 'x'), 'schema', *before)


class AttachReviseRename(Base):
    def setUp(self):
        super().setUp()
        self.seed({'plans': proposal(), 'other': proposal(evidence=())},
                  [{'name': 'nix-stuff', 'reason': 'too broad', 'date': '2026-12-03'}])
        self.init()

    def test_attach_and_its_idempotency(self):
        n = self.commits()
        out = self.ok(self.props('attach', '--name', 'plans', '--source', 'journal/2026-11-22', '--quote', 'More plans.'))
        self.assertEqual(out['evidence'], 2)
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(attach): plans <- journal/2026-11-22')
        before = self.state()
        self.assertEqual(self.ok(self.props('attach', '--name', 'plans', '--source', E1['source'], '--quote', E1['quote'])),
                         {'status': 'unchanged'})
        self.assertEqual(self.state(), before)
        self.assert_refused(self.props('attach', '--name', 'nope', '--source', 's', '--quote', 'q'), 'no open proposal', *before)
        self.assert_refused(self.props('attach', '--name', 'plans'), 'needs --source', *before)

    def test_attach_many_from_a_file_is_one_commit(self):
        m = self.tmp / 'evidence.json'
        m.write_text(json.dumps([{'source': 'journal/2026-11-22', 'quote': 'One.', 'note': 'one'},
                                 {'source': E1['source'], 'quote': E1['quote']},
                                 {'source': 'journal/2026-11-23', 'quote': 'Two.'}]))
        n = self.commits()
        out = self.ok(self.props('attach', '--name', 'plans', '--evidence', m))
        self.assertEqual((out['added'], out['evidence']), (2, 3))
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(attach): plans <- 2 records')
        before = self.state()
        self.assert_refused(self.props('attach', '--name', 'plans', '--evidence', m, '--source', 's'), 'replaces', *before)
        m.write_text('[]')
        self.assert_refused(self.props('attach', '--name', 'plans', '--evidence', m), 'non-empty', *before)
        m.write_text(json.dumps([{'source': 's'}]))
        self.assert_refused(self.props('attach', '--name', 'plans', '--evidence', m), 'source and quote', *before)

    def test_revise(self):
        self.ok(self.props('revise', '--name', 'plans', '--when-to-apply', 'Sequencing of future work.'))
        self.assertEqual(self.data()['proposals']['plans']['when_to_apply'], 'Sequencing of future work.')
        before = self.state()
        self.assertEqual(self.ok(self.props('revise', '--name', 'plans', '--when-to-apply', 'Sequencing of future work.')),
                         {'status': 'unchanged'})
        self.assert_refused(self.props('revise', '--name', 'nope', '--when-to-apply', 'x'), 'no open proposal', *before)

    def test_rename_keeps_place_and_content_and_touches_no_note(self):
        self.note('n', ['needs-label'])
        self.init()
        n = self.commits()
        self.ok(self.props('rename', '--from', 'plans', '--to', 'planning'))
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(rename): plans -> planning')
        data = self.data()['proposals']
        self.assertEqual(list(data), ['planning', 'other'])
        self.assertEqual(data['planning'], proposal())

    def test_rename_refusals(self):
        before = self.state()
        self.assert_refused(self.props('rename', '--from', 'plans', '--to', 'other'), 'already an open proposal', *before)
        self.assert_refused(self.props('rename', '--from', 'plans', '--to', 'roadmap'), 'already a label', *before)
        self.assert_refused(self.props('rename', '--from', 'plans', '--to', 'nix-stuff'), 'rejected', *before)
        self.assert_refused(self.props('rename', '--from', 'plans', '--to', 'Bad'), 'not a valid label name', *before)
        self.assert_refused(self.props('rename', '--from', 'nope', '--to', 'x'), 'no open proposal', *before)


class Merge(Base):
    def setUp(self):
        super().setUp()
        e2 = {'source': 'journal/2026-11-25', 'quote': 'Later.', 'note': 'later', 'added': '2026-11-25'}
        self.seed({'plans': proposal('explicit', (E1, e2), opened='2026-11-20'),
                   'planning': proposal('implicit', (E1,), opened='2026-11-24', text='Kept text.')})
        self.init()

    def test_into_a_proposal_unions_evidence_explicit_wins_earliest_opened(self):
        out = self.ok(self.props('merge', '--from', 'plans', '--into', 'planning'))
        self.assertEqual(out['kind'], 'proposal')
        data = self.data()
        self.assertNotIn('plans', data['proposals'])
        p = data['proposals']['planning']
        self.assertEqual(p['when_to_apply'], 'Kept text.')
        self.assertEqual(p['origin'], 'explicit')
        self.assertEqual(p['opened'], '2026-11-20')
        self.assertEqual([e['quote'] for e in p['evidence']], [E1['quote'], 'Later.'])
        self.assertEqual(data['rejected'], [])

    def test_into_an_active_label_closes_it_and_remembers_why(self):
        n = self.commits()
        out = self.ok(self.props('merge', '--from', 'plans', '--into', 'roadmap'))
        self.assertEqual((out['kind'], out['evidence_notes']), ('label', ['later', 'sketch-the-bed-layout']))
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(merge): plans into label roadmap')
        data = self.data()
        self.assertNotIn('plans', data['proposals'])
        self.assertEqual(data['rejected'], [{'name': 'plans', 'reason': 'merged into existing label roadmap', 'date': TODAY}])
        self.assertNotIn('plans', self.labels())

    def test_refusals(self):
        before = self.state()
        self.assert_refused(self.props('merge', '--from', 'plans', '--into', 'plans'), 'itself', *before)
        self.assert_refused(self.props('merge', '--from', 'plans', '--into', 'old-thing'), 'neither', *before)
        self.assert_refused(self.props('merge', '--from', 'plans', '--into', 'nowhere'), 'neither', *before)
        self.assert_refused(self.props('merge', '--from', 'nope', '--into', 'planning'), 'no open proposal', *before)


class Accept(Base):
    def setUp(self):
        super().setUp()
        self.seed({'plans': proposal('explicit'), 'other': proposal()},
                  [{'name': 'gone', 'reason': 'r', 'date': '2026-01-01'}])

    def test_accept_is_one_commit_over_the_bank_and_the_proposal_bank(self):
        self.init()
        n = self.commits()
        out = self.ok(self.props('accept', '--name', 'plans'))
        self.assertEqual(out['evidence_notes'], ['sketch-the-bed-layout'])
        self.one_commit(n, ['_machine/label-proposals.yml', '_machine/labels.yml'], 'label-proposals(accept): plans (proposal)')
        self.assertEqual(self.labels()['plans'], {'when_to_apply': 'Plans and sequencing.', 'status': 'active'})
        self.assertEqual(list(self.data()['proposals']), ['other'])
        self.assertTrue(self.bank_path.read_text().startswith('# my header\n'))

    def test_accept_may_reword(self):
        self.init()
        self.ok(self.props('accept', '--name', 'plans', '--when-to-apply', 'Final wording.'))
        self.assertEqual(self.labels()['plans']['when_to_apply'], 'Final wording.')

    def test_on_the_spot_acceptance_of_an_explicit_request(self):
        self.init()
        self.ok(self.props('accept', '--name', 'gone', '--explicit', '--when-to-apply', 'Back after all.'))
        self.assertEqual(self.labels()['gone']['status'], 'active')
        self.assertEqual(self.data()['rejected'], [])
        self.assertIn('(on the spot)', self.last_description())

    def test_refusals_change_nothing(self):
        self.init()
        before = self.state()
        self.assert_refused(self.props('accept', '--name', 'nope'), 'no open proposal', *before)
        self.assert_refused(self.props('accept', '--name', 'nope', '--explicit'), 'no open proposal', *before)
        self.assert_refused(self.props('accept', '--name', 'roadmap', '--explicit', '--when-to-apply', 'x'), 'already a label', *before)
        self.assert_refused(self.props('accept', '--name', 'plans', '--when-to-apply', ' '), 'schema', *before)
        self.bank_path.write_text(self.bank_path.read_text() + '\n')
        before = self.state()
        self.assert_refused(self.props('accept', '--name', 'plans'), 'uncommitted', *before)

    def test_a_failed_commit_rolls_both_files_back(self):
        self.init()
        shim = self.tmp / 'shim'
        shim.mkdir()
        real = shutil.which('jj')
        (shim / 'jj').write_text(f'#!/bin/sh\n[ "$2" = commit ] && {{ echo "commit refused by test" >&2; exit 1; }}\nexec "{real}" "$@"\n')
        (shim / 'jj').chmod(0o755)
        before = self.state()
        r = self.run_script_env({'PATH': f'{shim}:{os.environ["PATH"]}'}, 'label-proposals', 'accept', self.vault, '--name', 'plans')
        self.assert_refused(r, 'nothing changed', *before)
        self.assertIn('commit refused by test', r.stderr)

    def run_script_env(self, env, *args):
        import subprocess
        return subprocess.run([str(tl.SCRIPTS / args[0]), *map(str, args[1:])], capture_output=True, text=True,
                              env=dict(os.environ, **env))


class Reject(Base):
    def test_reject_records_and_blocks_an_implicit_reopen(self):
        self.seed({'plans': proposal()})
        self.init()
        n = self.commits()
        self.ok(self.props('reject', '--name', 'plans', '--reason', 'covered by roadmap'))
        self.one_commit(n, ['_machine/label-proposals.yml'], 'label-proposals(reject): plans')
        data = self.data()
        self.assertEqual(data['proposals'], {})
        self.assertEqual(data['rejected'], [{'name': 'plans', 'reason': 'covered by roadmap', 'date': TODAY}])
        before = self.state()
        self.assert_refused(self.props('open', '--name', 'plans', '--when-to-apply', 'x'), 'covered by roadmap', *before)
        self.assert_refused(self.props('reject', '--name', 'plans', '--reason', 'again'), 'no open proposal', *before)
        self.assert_refused(self.props('reject', '--name', 'x'), 'required', *before)


class Apply(Base):
    """Ingest's batch: idempotent, never commits, never accepts."""

    def setUp(self):
        super().setUp()
        self.seed({'plans': proposal()}, [{'name': 'nix-stuff', 'reason': 'too broad', 'date': '2026-12-03'}])
        self.init()

    def apply(self, requests):
        m = self.tmp / 'requests.json'
        m.write_text(json.dumps(requests))
        n = self.commits()
        out = self.ok(self.props('apply', m))
        self.assertEqual(self.commits(), n, 'apply committed')
        return out

    def req(self, name, origin='implicit', quote='a quote', **kw):
        return dict({'op': 'open', 'name': name, 'origin': origin, 'source': 'journal/2026-11-26', 'quote': quote,
                     'note': 'a-note', 'ref': 'r1', 'when_to_apply': 'Drafted.'}, **kw)

    def results(self, out):
        return [(r['name'], r['result']) for r in out['results']]

    def test_the_table(self):
        out = self.apply([self.req('fresh', 'explicit'), self.req('plans', 'explicit', op='attach'),
                          self.req('roadmap'), self.req('old-thing', 'explicit'), self.req('nix-stuff'),
                          self.req('Nix Stuff Two', 'explicit'), self.req('nameless', when_to_apply=None),
                          self.req('x', op='accept'), self.req('???')])
        self.assertEqual(self.results(out), [('fresh', 'opened'), ('plans', 'attached'), ('roadmap', 'skipped'),
                                             ('old-thing', 'skipped'), ('nix-stuff', 'skipped'),
                                             ('nix-stuff-two', 'opened'), ('nameless', 'failed'), ('x', 'failed'),
                                             ('???', 'failed')])
        self.assertEqual(out['results'][5]['normalised_from'], 'Nix Stuff Two')
        self.assertIn('never revived', out['results'][3]['reason'])
        self.assertIn('too broad', out['results'][4]['reason'])
        self.assertTrue(out['changed'] and out['dirty'])
        data = self.data()['proposals']
        self.assertEqual(data['fresh'], {'when_to_apply': 'Drafted.', 'origin': 'explicit', 'opened': TODAY, 'evidence': [
            {'source': 'journal/2026-11-26', 'quote': 'a quote', 'note': 'a-note', 'added': TODAY}]})
        self.assertEqual(data['plans']['origin'], 'explicit')  # an explicit request upgrades an implicit proposal
        self.assertEqual(len(data['plans']['evidence']), 2)
        self.assertNotIn('roadmap', data)
        self.assertNotIn('x', self.labels())

    def test_an_explicit_request_reopens_a_rejected_name(self):
        out = self.apply([self.req('nix-stuff', 'explicit')])
        self.assertEqual(self.results(out), [('nix-stuff', 'reopened')])
        self.assertIn('too broad', out['results'][0]['reason'])
        data = self.data()
        self.assertEqual(data['rejected'], [])
        self.assertEqual(data['proposals']['nix-stuff']['reopened'], {'reason': 'too broad', 'date': '2026-12-03'})

    def test_a_retry_changes_nothing_twice(self):
        reqs = [self.req('fresh'), self.req('plans', op='attach')]
        self.apply(reqs)
        text = self.props_path.read_text()
        out = self.apply(reqs)
        self.assertEqual(self.results(out), [('fresh', 'unchanged'), ('plans', 'unchanged')])
        self.assertFalse(out['changed'])
        self.assertTrue(out['dirty'])  # still uncommitted from the first apply: the run commit will carry it
        self.assertEqual(self.props_path.read_text(), text)

    def test_nothing_to_change_writes_nothing(self):
        out = self.apply([self.req('roadmap')])
        self.assertEqual((out['changed'], out['dirty']), (False, False))


class Stats(Base):
    def test_counts_and_history(self):
        two = (E1, dict(E1, quote='again'))
        self.seed({'a': proposal('explicit', ()), 'b': proposal('implicit', two), 'c': proposal('implicit'),
                   'd': proposal('implicit')})
        self.init()
        self.ok(self.props('accept', '--name', 'd'))
        self.ok(self.props('reject', '--name', 'c', '--reason', 'no'))
        out = self.ok(self.props('stats'))
        self.assertEqual(out, {'open': 2, 'explicit': 1, 'implicit': 1, 'two_or_more': 1, 'waiting': 0,
                               'rejected_remembered': 1, 'accepted': 1, 'rejected': 1})


if __name__ == '__main__':
    unittest.main()
