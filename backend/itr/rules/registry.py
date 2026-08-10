"""
The versioned rule registry.

ARCHITECTURE MANDATE 1 / ACCEPTANCE CRITERION 7: a new CBDT rule is added by
editing a JSON file in `itr/data/ay2026-27/rules/` and adding a fixture. No
code change and no redeployment of application logic is required.

Ported from itr1-module/packages/core/src/rules/registry.ts. Templated
entries (`$template`) exist because ~60 CBDT rules are the same assertion
with a different section or dropdown value; the template expands to a full
rule at load time so the loaded registry is homogeneous.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from itr.engine.evaluator import ExpressionError, assert_compiles

DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'ay2026-27' / 'rules'

RULE_SET_VERSION = 'rules-ay2026-27-1.0.0'

SEVERITY_BY_CATEGORY = {'A': 'BLOCK', 'B': 'ADVISORY', 'D': 'DOCUMENT'}

_INTERPOLATE_RE = re.compile(r'\{\{(\w+)\}\}')


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    ay: str
    screen: str
    tier: int
    scope: str
    fields: tuple
    appliesWhen: str
    assert_: str
    severity: str
    message: str
    remediation: str
    deepLink: str
    values: dict = field(default_factory=dict)
    source: str = ''
    note: str | None = None
    advisory: str | None = None
    aliasOf: str | None = None


def _interpolate(text, params):
    def repl(m):
        key = m.group(1)
        return str(params[key]) if key in params else m.group(0)

    return _INTERPOLATE_RE.sub(repl, text)


def _load_json(name):
    with open(DATA_DIR / name, encoding='utf-8') as f:
        return json.load(f)


def _expand_template(entry, templates):
    name = entry['$template']
    tpl = templates.get(name)
    if tpl is None:
        raise ValueError(f"Rule {entry.get('id')}: unknown template \"{name}\"")

    params = {k: v for k, v in entry.items() if k != '$template'}

    out = {}
    for k, v in tpl.items():
        if isinstance(v, str):
            out[k] = _interpolate(v, params)
        elif isinstance(v, list):
            out[k] = [_interpolate(x, params) if isinstance(x, str) else x for x in v]
        elif isinstance(v, dict):
            out[k] = {vk: _interpolate(vv, params) for vk, vv in v.items()}
        else:
            out[k] = v

    for k, v in params.items():
        if k == 'id' or k not in out:
            out[k] = v
    out['id'] = entry['id']
    return out


def _normalise(raw, category, templates):
    e = _expand_template(raw, templates) if '$template' in raw else raw
    return Rule(
        id=str(e['id']),
        category=category,
        ay='2026-27',
        screen=str(e['screen']),
        tier=int(e.get('tier', 3)),
        scope=str(e.get('scope', 'MODEL')),
        fields=tuple(e.get('fields', [])),
        appliesWhen=str(e.get('appliesWhen', 'true')),
        assert_=str(e['assert']),
        severity=str(e.get('severity', SEVERITY_BY_CATEGORY[category])),
        message=str(e['message']),
        remediation=str(e.get('remediation', '')),
        deepLink=str(e.get('deepLink', '')),
        values=dict(e.get('values', {})),
        source=str(e.get('source', '')),
        note=str(e['note']) if e.get('note') else None,
        advisory=str(e['advisory']) if e.get('advisory') else None,
        aliasOf=str(e['aliasOf']) if e.get('aliasOf') else None,
    )


@lru_cache(maxsize=1)
def _load():
    templates = _load_json('templates.json')
    chunks_a = [
        _load_json('category-a-001-100.json'),
        _load_json('category-a-101-200.json'),
        _load_json('category-a-201-300.json'),
        _load_json('category-a-301-339.json'),
    ]
    b = _load_json('category-b.json')
    d = _load_json('category-d.json')

    rules = []
    for chunk in chunks_a:
        for raw in chunk:
            rules.append(_normalise(raw, 'A', templates))
    for raw in b:
        rules.append(_normalise(raw, 'B', templates))
    for raw in d:
        rules.append(_normalise(raw, 'D', templates))
    return tuple(rules)


def rules():
    return _load()


def rules_by_id():
    return {r.id: r for r in rules()}


def rules_for_screen(screen):
    return [r for r in rules() if r.screen == screen]


def validate_registry():
    """Static self-check run by tests and at server boot: every rule must
    have a unique id, a compiling expression pair, a non-empty message and a
    deep link. A malformed rule file must fail loudly, not silently skip
    rules."""
    problems = []
    seen = set()
    id_re = re.compile(r'^[ABD]-\d+$')
    for r in rules():
        if r.id in seen:
            problems.append(f'Duplicate rule id {r.id}')
        seen.add(r.id)
        if not id_re.match(r.id):
            problems.append(f'Malformed rule id {r.id}')
        if not r.message:
            problems.append(f'{r.id}: empty message')
        if not r.deepLink:
            problems.append(f'{r.id}: missing deepLink')
        if not r.source:
            problems.append(f'{r.id}: missing verbatim CBDT source text')
        try:
            assert_compiles(r.appliesWhen)
        except ExpressionError as e:
            problems.append(f'{r.id}: appliesWhen does not compile - {e}')
        try:
            assert_compiles(r.assert_)
        except ExpressionError as e:
            problems.append(f'{r.id}: assert does not compile - {e}')
        for k, expr in r.values.items():
            try:
                assert_compiles(expr)
            except ExpressionError as e:
                problems.append(f'{r.id}: values.{k} does not compile - {e}')
    return problems


def registry_counts():
    all_rules = rules()
    return {
        'A': sum(1 for r in all_rules if r.category == 'A'),
        'B': sum(1 for r in all_rules if r.category == 'B'),
        'D': sum(1 for r in all_rules if r.category == 'D'),
        'total': len(all_rules),
    }
