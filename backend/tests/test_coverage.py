"""Rule coverage: every rule in the registry must have a passing fixture (a
return under which it is live and satisfied) and a failing fixture (a
perturbation under which it fires).

Sec 12.1(16): "A rule with no failing fixture is an untested rule."

Ported from itr1-module/packages/core/test/coverage.test.ts.
"""

from itr1.engine.compute import compute
from itr1.engine.evaluator import evaluate_boolean
from itr1.engine.facts import build_facts
from itr1.engine.payload_facts import build_payload_facts
from itr1.rules.registry import rules
from itr1.serialize.serializer import serialize
from tests.fixtures.coverage_bases import COVERAGE_BASES
from tests.fixtures.falsify import evaluate_values, falsify


def _build_base_facts():
    out = []
    for base in COVERAGE_BASES:
        m = base['build']()
        c = compute(m)
        result = serialize(m, {'creationDate': '2026-08-07', 'computed': c})
        out.append(
            {
                'name': base['name'],
                'model': build_facts(m, c),
                'payload': build_payload_facts(result['payload']),
            }
        )
    return out


BASE_FACTS = _build_base_facts()
RULES = rules()


class Outcome:
    def __init__(self, rule_id):
        self.rule_id = rule_id
        self.passing_base = None
        self.failing = None
        self.reason = None


def _analyse():
    outcomes = []
    for rule in RULES:
        outcome = Outcome(rule.id)

        for base in BASE_FACTS:
            facts = base['payload'] if rule.scope == 'PAYLOAD' else base['model']
            try:
                live = evaluate_boolean(rule.appliesWhen, facts)
                if not live:
                    continue
                holds = evaluate_boolean(rule.assert_, facts)
            except Exception as e:  # noqa: BLE001 - mirror TS catch-all
                outcome.reason = f'expression error on base {base["name"]}: {e}'
                continue

            if holds and not outcome.passing_base:
                outcome.passing_base = base['name']

            if not outcome.failing:
                if not holds:
                    # The base itself already falsifies the rule -- that is
                    # a failing fixture.
                    outcome.failing = {'base': base['name'], 'variable': '(base)', 'change': 'base return'}
                else:
                    f = falsify(rule, facts)
                    if f:
                        outcome.failing = {'base': base['name'], 'variable': f.variable, 'change': f.change}

            if outcome.passing_base and outcome.failing:
                break

        if not outcome.passing_base and not outcome.reason:
            outcome.reason = 'no base makes this rule live with its assertion satisfied'
        outcomes.append(outcome)
    return outcomes


OUTCOMES = _analyse()


def test_has_a_passing_fixture_for_every_rule():
    uncovered = [f'{o.rule_id} - {o.reason or "not live under any base"}' for o in OUTCOMES if not o.passing_base]
    assert uncovered == []


def test_has_a_failing_fixture_for_every_rule_no_rule_is_a_tautology():
    unfalsifiable = [o.rule_id for o in OUTCOMES if not o.failing]
    assert unfalsifiable == []


def test_reports_100_percent_rule_coverage():
    covered = sum(1 for o in OUTCOMES if o.passing_base and o.failing)
    print(f'Rule coverage: {covered}/{len(RULES)}')
    assert covered == len(RULES)


def test_produces_a_message_that_names_offending_and_permitted_value():
    bad = []
    for rule in RULES:
        if not rule.values:
            continue
        base = None
        for b in BASE_FACTS:
            facts = b['payload'] if rule.scope == 'PAYLOAD' else b['model']
            try:
                if evaluate_boolean(rule.appliesWhen, facts):
                    base = b
                    break
            except Exception:
                continue
        if base is None:
            continue
        facts = base['payload'] if rule.scope == 'PAYLOAD' else base['model']
        f = falsify(rule, facts)
        if not f:
            continue
        values = evaluate_values(rule.values, f.facts)
        missing = [k for k, v in values.items() if v is None]
        if missing:
            bad.append(f'{rule.id}: values {", ".join(missing)} did not evaluate')
    assert bad == []
