"""The vault's routing file, <vault>/_machine/routing.yml: load, validate, match. Writes nothing.

Match semantics (unchanged from the routing this replaces): a rule holds when every term in its match holds. A term is
a pattern (a label, or a glob where * matches any run of characters; a bare * holds for every thought, even one with
no labels), {any: [patterns]} (some label matches some pattern) or {none: [patterns]} (no label matches any). Rules
are a set: every rule that holds delivers to every target in its to, each target once, in the order first reached.
"""
import json
import re
from pathlib import Path

import jsonschema
import yaml

ROUTING = '_machine/routing.yml'
NOTES = 'notes'  # the adapter that writes the vault copy; its result is the thought's id
SCHEMA = json.loads((Path(__file__).resolve().parent / 'routing.schema.json').read_text(encoding='utf-8'))


class RoutingError(Exception):
    """The routing file is absent or unusable. Nothing was routed."""


def holds_pattern(pattern, labels):
    if pattern == '*':
        return True
    regex = '.*'.join(re.escape(part) for part in pattern.split('*'))
    return any(re.fullmatch(regex, label) for label in labels)


def holds(term, labels):
    if isinstance(term, str):
        return holds_pattern(term, labels)
    if 'any' in term:
        return any(holds_pattern(p, labels) for p in term['any'])
    return not any(holds_pattern(p, labels) for p in term['none'])


class Routing:
    def __init__(self, data):
        self.targets = data['targets']
        self.rules = data['rules']

    def adapter(self, target):
        return self.targets[target]['adapter']

    def params(self, target):
        return self.targets[target].get('params', {})

    def is_notes(self, target):
        return self.adapter(target) == NOTES

    def route(self, labels):
        """Target names for a thought with LABELS, notes first, then in the order the rules reach them."""
        out = []
        for rule in self.rules:
            if all(holds(term, labels) for term in rule['match']):
                out += [t for t in rule['to'] if t not in out]
        return sorted(out, key=lambda t: not self.is_notes(t))

    def outbound_patterns(self):
        """Every pattern in a rule that delivers somewhere other than the notes adapter. A none term sends nothing
        anywhere, it only stops a rule firing, so it never makes a label outbound."""
        found = set()
        for rule in self.rules:
            if all(self.is_notes(t) for t in rule['to']):
                continue
            for term in rule['match']:
                if isinstance(term, str):
                    found.add(term)
                elif 'any' in term:
                    found.update(term['any'])
        return found

    def is_outbound(self, label):
        return any(holds_pattern(p, [label]) for p in self.outbound_patterns())


def load(vault):
    path = Path(vault) / ROUTING
    if not path.is_file():
        raise RoutingError(f'no routing file at {ROUTING}')
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise RoutingError(f'{ROUTING} does not parse: ' + ' '.join(str(e).split())[:160])
    error = jsonschema.exceptions.best_match(jsonschema.Draft7Validator(SCHEMA).iter_errors(data))
    if error is not None:
        where = '/'.join(str(p) for p in error.absolute_path) or '(root)'
        raise RoutingError(f'{ROUTING} fails its schema at {where}: {error.message}')
    undeclared = sorted({t for r in data['rules'] for t in r['to'] if t not in data['targets']})
    if undeclared:
        raise RoutingError(f'{ROUTING}: rules name undeclared targets: {", ".join(undeclared)}')
    notes = [name for name, t in data['targets'].items() if t['adapter'] == NOTES]
    if len(notes) > 1:
        raise RoutingError(f'{ROUTING}: only one target may use the {NOTES} adapter, found {", ".join(notes)}')
    return Routing(data)
