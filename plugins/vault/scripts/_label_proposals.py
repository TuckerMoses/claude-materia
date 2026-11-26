"""The proposal bank, <vault>/_machine/label-proposals.yml, as library code. Shared by label-proposals and
ingest-status.

Every operation is a pure function from the proposals data (and, where it needs one, the label bank) to new data,
raising ProposalError to refuse. Nothing here commits: the caller lands Proposals.change() alone or beside a bank
change in one _vault_tx transaction, which is how accept puts the bank entry and the proposal's removal in one commit.
"""
import copy
import datetime
import json
import re
from pathlib import Path

import jsonschema
import yaml

import _label_bank as lb
import _vault_tx as tx

PROPOSALS = '_machine/label-proposals.yml'
SCHEMA = json.loads((Path(__file__).resolve().parent / 'label-proposals.schema.json').read_text(encoding='utf-8'))
NAME = re.compile(SCHEMA['definitions']['name']['pattern'])


class ProposalError(Exception):
    """Refused. Nothing changed."""


def today():
    return datetime.date.today().isoformat()


def _plain_dates(node):
    """Dates as ISO strings: a hand-written unquoted date parses as a date, the schema stores strings."""
    if isinstance(node, (datetime.date, datetime.datetime)):
        return node.isoformat()[:10]
    if isinstance(node, dict):
        return {k: _plain_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain_dates(v) for v in node]
    return node


def validate(data):
    error = jsonschema.exceptions.best_match(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))
    if error is not None:
        where = '/'.join(str(p) for p in error.absolute_path) or '(root)'
        raise ProposalError(f'proposal bank fails its schema at {where}: {error.message}')


def valid_name(name):
    return isinstance(name, str) and bool(NAME.match(name))


def normalise(name):
    """The nearest valid label name to NAME, or None. Lower case; runs of anything else become one hyphen."""
    if not isinstance(name, str):
        return None
    parts = name.strip().lower().split(':', 1)
    head = re.sub(r'[^a-z0-9/]+', '-', parts[0]).strip('-/')
    head = re.sub(r'/+', '/', re.sub(r'-*/-*', '/', head))
    out = head
    if len(parts) == 2:
        tail = re.sub(r'[^a-z0-9_]+', '-', parts[1]).strip('-_')
        out = f'{head}:{tail}' if tail else head
    return out if valid_name(out) else None


class Proposals:
    """The proposal bank as read: its text and stamp, for the write; its data, for everything else."""

    def __init__(self, vault):
        path = Path(vault) / PROPOSALS
        if not path.is_file():
            raise ProposalError(f'no proposal bank at {PROPOSALS}; stamp it from the vault template')
        self.text, self.stamp = tx.read(path)
        try:
            data = yaml.safe_load(self.text)
        except yaml.YAMLError as e:
            raise ProposalError('proposal bank does not parse: ' + ' '.join(str(e).split())[:160])
        self.data = _plain_dates(data)
        validate(self.data)

    @property
    def open(self):
        return self.data['proposals']

    def rejection(self, name):
        return next((r for r in self.data['rejected'] if r['name'] == name), None)

    def render(self, data):
        validate(data)
        new = lb.header(self.text) + lb.dump(data, fold=True)
        if _plain_dates(yaml.safe_load(new)) != data:
            raise ProposalError('proposal bank does not survive a round trip; nothing written')
        return new

    def change(self, data):
        """A Change replacing the file with DATA, validated before and after the write."""
        new = self.render(data)

        def check(back):
            validate(_plain_dates(yaml.safe_load(back)))
        return tx.Change(PROPOSALS, self.text, self.stamp, new, check)


# --- operations --------------------------------------------------------------------------------------------------

def evidence(source, quote, note=None, added=None):
    if not (isinstance(source, str) and source.strip() and isinstance(quote, str) and quote.strip()):
        raise ProposalError('evidence needs a non-empty source and quote')
    e = {'source': source, 'quote': quote}
    if note:
        e['note'] = note
    e['added'] = added or today()
    return e


def _same(a, b):
    return a['source'] == b['source'] and a['quote'] == b['quote']


def _add_evidence(proposal, records):
    """PROPOSAL with RECORDS appended, skipping any with the same source and quote. Returns how many were new."""
    added = 0
    for r in records:
        if not any(_same(r, e) for e in proposal['evidence']):
            proposal['evidence'].append(r)
            added += 1
    return added


def _refuse_bad_new_name(data, bank, name):
    if not valid_name(name):
        hint = normalise(name)
        raise ProposalError(f'{name!r} is not a valid label name' + (f'; did you mean {hint}?' if hint else ''))
    if name in data['proposals']:
        raise ProposalError(f'{name} is already an open proposal; attach evidence to it instead')
    if name in bank.labels:
        status = bank.labels[name]['status']
        raise ProposalError(f'{name} is already a label (status {status})'
                            + ('; apply it instead' if status == 'active' else '; a retired label is never revived'))


def op_open(data, bank, name, when_to_apply, explicit, records=()):
    _refuse_bad_new_name(data, bank, name)
    data = copy.deepcopy(data)
    proposal = {'when_to_apply': when_to_apply, 'origin': 'explicit' if explicit else 'implicit', 'opened': today()}
    old = next((r for r in data['rejected'] if r['name'] == name), None)
    if old:
        if not explicit:
            raise ProposalError(f'{name} was rejected on {old["date"]} ({old["reason"]}); only an explicit request reopens it')
        proposal['reopened'] = {'reason': old['reason'], 'date': old['date']}
        data['rejected'] = [r for r in data['rejected'] if r['name'] != name]
    proposal['evidence'] = []
    _add_evidence(proposal, list(records))
    data['proposals'][name] = proposal
    return data


def _proposal(data, name):
    if name not in data['proposals']:
        raise ProposalError(f'no open proposal named {name}')
    return data['proposals'][name]


def op_attach(data, name, records):
    _proposal(data, name)
    data = copy.deepcopy(data)
    return data, _add_evidence(data['proposals'][name], records)


def op_revise(data, name, when_to_apply):
    _proposal(data, name)
    data = copy.deepcopy(data)
    data['proposals'][name]['when_to_apply'] = when_to_apply
    return data


def op_rename(data, bank, old, new):
    _proposal(data, old)
    _refuse_bad_new_name(data, bank, new)
    gone = next((r for r in data['rejected'] if r['name'] == new), None)
    if gone:
        raise ProposalError(f'{new} was rejected on {gone["date"]} ({gone["reason"]})')
    data = copy.deepcopy(data)
    data['proposals'] = {(new if k == old else k): v for k, v in data['proposals'].items()}
    return data


def op_merge(data, bank, source, into):
    """SOURCE into another open proposal (evidence unioned, INTO's text kept, explicit if either was) or into an active
    label (SOURCE closes and is remembered as rejected, so ingest does not reopen it). Returns (data, kind)."""
    if source == into:
        raise ProposalError('a proposal cannot be merged into itself')
    absorbed = _proposal(data, source)
    data = copy.deepcopy(data)
    del data['proposals'][source]
    if into in data['proposals']:
        survivor = data['proposals'][into]
        _add_evidence(survivor, absorbed['evidence'])
        if absorbed['origin'] == 'explicit':
            survivor['origin'] = 'explicit'
        survivor['opened'] = min(survivor['opened'], absorbed['opened'])
        return data, 'proposal'
    if bank.active(into):
        data['rejected'] = [r for r in data['rejected'] if r['name'] != source]
        data['rejected'].append({'name': source, 'reason': f'merged into existing label {into}', 'date': today()})
        return data, 'label'
    raise ProposalError(f'{into} is neither an open proposal nor an active label')


def op_reject(data, name, reason):
    _proposal(data, name)
    data = copy.deepcopy(data)
    del data['proposals'][name]
    data['rejected'] = [r for r in data['rejected'] if r['name'] != name]
    data['rejected'].append({'name': name, 'reason': reason, 'date': today()})
    return data


def op_accept(data, bank, name, when_to_apply=None, explicit=False):
    """(new proposals data, new bank labels). An open proposal becomes an active local label; with EXPLICIT and a
    WHEN_TO_APPLY, a name with no proposal yet is accepted on the spot (the interactive gate)."""
    if name in bank.labels:
        raise ProposalError(f'{name} is already a label (status {bank.labels[name]["status"]})')
    data = copy.deepcopy(data)
    if name in data['proposals']:
        text = when_to_apply or data['proposals'][name]['when_to_apply']
        del data['proposals'][name]
    elif explicit and when_to_apply:
        if not valid_name(name):
            raise ProposalError(f'{name!r} is not a valid label name')
        text = when_to_apply
    else:
        raise ProposalError(f'no open proposal named {name}')
    data['rejected'] = [r for r in data['rejected'] if r['name'] != name]
    labels = dict(bank.labels)
    labels[name] = {'when_to_apply': text, 'status': 'active'}
    return data, labels


# --- ingest's batch: idempotent open/attach, no commit -----------------------------------------------------------

def apply_requests(data, bank, requests):
    """Ingest's proposal writes for one run. Each request is {op: open|attach, name, origin, when_to_apply?, source,
    quote, note?, ref?}. Idempotent, so a retried run changes nothing twice: an open of an open proposal attaches; an
    attach of evidence already there is unchanged. Never accepts. Returns (data, results), one result per request:
    {ref, name, result: opened|reopened|attached|unchanged|skipped|failed, reason?, normalised_from?}."""
    data = copy.deepcopy(data)
    results = []
    for req in requests:
        res = {'ref': req.get('ref'), 'name': req.get('name')}
        results.append(res)
        try:
            if req.get('op') not in ('open', 'attach'):
                raise ProposalError(f'ingest may only open or attach, not {req.get("op")!r}')
            if req.get('origin') not in ('explicit', 'implicit'):
                raise ProposalError('origin must be explicit or implicit')
            name = req['name']
            if not valid_name(name):
                fixed = normalise(name)
                if fixed is None:
                    raise ProposalError(f'{name!r} is not a valid label name and has no normal form')
                res.update(name=fixed, normalised_from=name)
                name = fixed
            record = evidence(req.get('source'), req.get('quote'), req.get('note'))
            explicit = req['origin'] == 'explicit'
            if name in bank.labels:
                status = bank.labels[name]['status']
                res.update(result='skipped', reason=f'{name} is an {status} label' + (
                    '; apply it' if status == 'active' else '; a retired label is never revived'))
                continue
            if name in data['proposals']:
                proposal = data['proposals'][name]
                new = _add_evidence(proposal, [record])
                upgraded = explicit and proposal['origin'] == 'implicit'
                if upgraded:
                    proposal['origin'] = 'explicit'
                res['result'] = 'attached' if new or upgraded else 'unchanged'
                continue
            old = next((r for r in data['rejected'] if r['name'] == name), None)
            if old and not explicit:
                res.update(result='skipped', reason=f'{name} was rejected on {old["date"]}: {old["reason"]}')
                continue
            text = req.get('when_to_apply')
            if not (isinstance(text, str) and text.strip()):
                raise ProposalError(f'opening {name} needs a drafted when_to_apply')
            data = op_open(data, bank, name, text, explicit, [record])
            res['result'] = 'reopened' if old else 'opened'
            if old:
                res['reason'] = f'rejected on {old["date"]}: {old["reason"]}'
        except (ProposalError, KeyError, TypeError) as e:
            res.update(result='failed', reason=str(e))
    return data, results


def write_uncommitted(vault, change):
    """Land CHANGE without a commit: ingest's run commit carries it. Validated on the text read back."""
    path = Path(vault) / change.rel
    tx._replace(path, change.new, change.stamp)
    back, _ = tx.read(path)
    if back != change.new:
        tx._replace(path, change.old)
        raise ProposalError(f'{change.rel} did not read back as written; restored')
    change.check(back)


# --- read-only counts --------------------------------------------------------------------------------------------

def counts(data):
    props = data['proposals'].values()
    return {'open': len(data['proposals']),
            'explicit': sum(1 for p in props if p['origin'] == 'explicit'),
            'implicit': sum(1 for p in props if p['origin'] == 'implicit'),
            'two_or_more': sum(1 for p in props if len(p['evidence']) >= 2),
            'waiting': sum(1 for p in props if p['origin'] == 'implicit' and len(p['evidence']) < 2),
            'rejected_remembered': len(data['rejected'])}


def evidence_notes(data):
    """Slugs named as evidence by any open proposal."""
    return {e['note'] for p in data['proposals'].values() for e in p['evidence'] if e.get('note')}
