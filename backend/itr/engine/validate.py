"""
The validation engine.

Ported from itr1-module/packages/core/src/engine/validate.ts.

ARCHITECTURE MANDATE 4 -- three tiers, one registry:
  Tier 1  field-level, on blur      -- format, length, regex, range
  Tier 2  screen-level, on Confirm  -- cross-field rules confined to the screen
  Tier 3  return-level              -- every rule, including cross-screen

A rule declares the LOWEST tier at which it is reachable and fires
identically at that tier and every tier above it. No rule exists only at
Tier 3: tier 3 is the union of all tiers, so a tier-1 rule is re-evaluated
there too.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from itr.engine.compute import compute
from itr.engine.evaluator import ExpressionError, evaluate, evaluate_boolean
from itr.engine.facts import build_facts
from itr.engine.payload_facts import build_payload_facts
from itr.rules.registry import RULE_SET_VERSION, rules as all_rules
from itr.util.num import format_indian

SCREEN_ORDER = [
    'PERSONAL_INFO',
    'GROSS_TOTAL_INCOME',
    'TOTAL_DEDUCTIONS',
    'TAX_PAID',
    'TAX_LIABILITY',
    'TAX_SUMMARY',
    'VALIDATION',
]

_RUPEE_KEYS = re.compile(
    r'amount|claimed|limit|eligible|entered|total|expected|gti|ti|paid|payable|rebate|'
    r'relief|refund|value|cap|sum|salary|gross|net|fee|interest|deduction|savings|hra|'
    r'schedule|rowSum|threshold',
    re.IGNORECASE,
)

_INTERPOLATE_RE = re.compile(r'\{\{(\w+)\}\}')


@dataclass
class Finding:
    ruleId: str
    category: str
    severity: str
    screen: str
    tier: int
    message: str
    remediation: str
    deepLink: str
    fields: tuple
    values: dict
    source: str
    aliasOf: str | None = None
    # Not set by validate() itself -- resolve_deep_link(deepLink) fills this
    # in downstream (itr.services.return_service.run_validation) once a
    # return_id is known. Declared here (rather than a dynamic attribute) so
    # every consumer can read it directly instead of a defensive getattr.
    goto_url: str | None = None


@dataclass
class ValidationReport:
    ok: bool
    errors: list = field(default_factory=list)
    advisories: list = field(default_factory=list)
    documentAdvisories: list = field(default_factory=list)
    ruleErrors: list = field(default_factory=list)
    tier: int = 3
    screen: str | None = None
    ruleSetVersion: str = RULE_SET_VERSION
    constantsVersion: str = ''
    rulesEvaluated: int = 0
    rulesSkipped: int = 0
    evaluatedAt: str = ''


def _format_value(key, v):
    if v is None:
        return '—'
    if isinstance(v, (list, tuple)):
        return ', '.join(str(x) for x in v) if v else '—'
    if isinstance(v, bool):
        return 'Yes' if v else 'No'
    if isinstance(v, (int, float)):
        if _RUPEE_KEYS.search(key) and abs(v) >= 100:
            return f'₹{format_indian(v)}'
        return str(v)
    return str(v)


def _interpolate(text, values):
    def repl(m):
        key = m.group(1)
        return values[key] if key in values else m.group(0)

    return _INTERPOLATE_RE.sub(repl, text)


def _touches_fields(rule, fields):
    """Does this rule read any of `fields`? Prefix match, so `income` matches
    `income.salary17_1`."""
    if not fields:
        return True
    for rf in rule.fields:
        for f in fields:
            if rf == f or rf.startswith(f + '.') or f.startswith(rf + '.'):
                return True
    return False


def _select_rules(tier, screen=None, fields=None):
    selected = [r for r in all_rules() if r.tier <= tier]
    if tier < 3 and screen:
        selected = [r for r in selected if r.screen == screen]
    if tier == 1 and fields:
        selected = [r for r in selected if _touches_fields(r, fields)]
    return selected, len(all_rules()) - len(selected)


def _numeric_id(rule_id):
    m = re.search(r'(\d+)$', rule_id)
    return int(m.group(1)) if m else 0


def validate(model, tier, screen=None, fields=None, payload=None, computed=None, now=None):
    """Run the three-tier validation runner against `model`.

    Mirrors validate.ts's `validate(model, opts)`; keyword arguments here
    correspond to the TS `ValidateOptions` fields.
    """
    computed = computed if computed is not None else compute(model)
    model_facts = build_facts(model, computed)
    payload_facts = build_payload_facts(payload) if payload is not None else None

    selected, skipped = _select_rules(tier, screen, fields)

    errors = []
    advisories = []
    document_advisories = []
    rule_errors = []
    evaluated = 0
    skipped_for_missing_payload = 0

    for rule in selected:
        facts = payload_facts if rule.scope == 'PAYLOAD' else model_facts
        if facts is None:
            # A PAYLOAD rule without a payload is not "passing" -- it is not evaluated.
            skipped_for_missing_payload += 1
            continue
        try:
            if not evaluate_boolean(rule.appliesWhen, facts):
                continue
            evaluated += 1
            if evaluate_boolean(rule.assert_, facts):
                continue

            values = {}
            for k, expr in rule.values.items():
                try:
                    values[k] = _format_value(k, evaluate(expr, facts))
                except ExpressionError:
                    values[k] = '—'

            finding = Finding(
                ruleId=rule.id,
                category=rule.category,
                severity=rule.severity,
                screen=rule.screen,
                tier=rule.tier,
                message=_interpolate(rule.message, values),
                remediation=_interpolate(rule.remediation, values),
                deepLink=rule.deepLink,
                fields=rule.fields,
                values=values,
                source=rule.source,
                aliasOf=rule.aliasOf,
            )

            if rule.category == 'A':
                errors.append(finding)
            elif rule.category == 'B':
                advisories.append(finding)
            else:
                document_advisories.append(finding)
        except ExpressionError as e:
            rule_errors.append({'ruleId': rule.id, 'error': str(e)})

    def by_sequence(f):
        return (SCREEN_ORDER.index(f.screen) if f.screen in SCREEN_ORDER else len(SCREEN_ORDER),
                _numeric_id(f.ruleId))

    errors.sort(key=by_sequence)
    advisories.sort(key=by_sequence)
    document_advisories.sort(key=by_sequence)

    evaluated_at = (now or datetime.now(timezone.utc)).isoformat()

    return ValidationReport(
        ok=len(errors) == 0 and len(rule_errors) == 0,
        errors=errors,
        advisories=advisories,
        documentAdvisories=document_advisories,
        ruleErrors=rule_errors,
        tier=tier,
        screen=screen,
        ruleSetVersion=RULE_SET_VERSION,
        constantsVersion=computed.get('constantsVersion', ''),
        rulesEvaluated=evaluated,
        rulesSkipped=skipped + skipped_for_missing_payload,
        evaluatedAt=evaluated_at,
    )


def group_by_screen(findings):
    """Group findings by screen for the Validation screen's presentation."""
    by_screen = {}
    for f in findings:
        by_screen.setdefault(f.screen, []).append(f)
    return [{'screen': s, 'findings': by_screen[s]} for s in SCREEN_ORDER if s in by_screen]


def unacknowledged_advisories(report, model):
    """Which advisories still need an explicit "I understand" acknowledgement
    before the JSON may be downloaded (Category B and D never block, but must
    be acknowledged and the acknowledgement stored in the audit log)."""
    acks = model.get('advisoryAcknowledgements', {})
    return [f for f in (report.advisories + report.documentAdvisories) if not acks.get(f.ruleId)]
