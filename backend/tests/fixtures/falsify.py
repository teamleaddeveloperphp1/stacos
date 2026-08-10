"""The falsifier.

ACCEPTANCE CRITERION 1 / §12.1(16): every rule needs a passing AND a failing
fixture. Hand-authoring hundreds of fixtures would be busywork and would not
actually prove more than this does: for each rule we find a return under
which the rule is live and its assertion holds (the passing fixture), then
search for the smallest perturbation of the facts it reads that makes the
assertion false while keeping it live (the failing fixture).

A rule with no discoverable falsification is a rule that can never fire --
i.e. a tautology -- and the coverage test fails on it rather than reporting
a pass.

Ported from itr1-module/packages/core/test/fixtures/falsify.ts.
"""

import ast
import copy
import re

from itr.engine.evaluator import HELPERS, evaluate, evaluate_boolean

FactBag = dict

# Names that are never "referenced variables": the boolean literal table the
# evaluator wires up, plus helper-function identifiers (a Name node that is
# only ever the `.func` of a Call is a function reference, not a variable).
_LITERAL_NAMES = {'true', 'false'}


def referenced_variables(expression):
    """Python port of the TS evaluator's `referencedVariables`, which (via
    expr-eval's `compile(expr).variables({ withMembers: false })`) returns
    the set of top-level identifiers an expression reads, collapsing dotted
    member access (`K.a.b.c`) down to its base name (`K`).

    `evaluator.py` does not expose an equivalent helper (it is a constrained
    file we may not modify), so this is implemented directly against the
    expression's Python-compatible AST -- the same grammar simpleeval parses
    the rule expressions with.
    """
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError:
        return []

    call_func_names = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    names = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        name = node.id
        if name in _LITERAL_NAMES:
            continue
        if name in call_func_names and name in HELPERS:
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


class Falsification:
    def __init__(self, variable, change, facts):
        self.variable = variable
        self.change = change
        self.facts = facts


def _literals_in(expression):
    """String literals written into the rule expression itself, e.g. 'NA',
    '10(2)'."""
    return re.findall(r"'([^']*)'", expression)


def _constant_arrays_in(expression, facts):
    """Array constants the expression reads out of `K`, e.g. the TDS
    advisory lists."""
    out = []
    for m in re.finditer(r'K\.([A-Za-z0-9_.]+)', expression):
        cur = facts.get('K')
        path = m.group(1).rstrip('.')
        for seg in path.split('.'):
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
            else:
                cur = None
                break
        if isinstance(cur, list) and len(cur):
            out.append(cur)
    return out


def _candidates_for(value):
    out = []

    if isinstance(value, bool):
        return [{'value': not value, 'label': f'{value} -> {not value}'}]

    if isinstance(value, (int, float)):
        out.extend(
            [
                {'value': value + 1, 'label': f'{value} -> {value + 1}'},
                {'value': value - 1, 'label': f'{value} -> {value - 1}'},
                {'value': value * 2 + 1, 'label': f'{value} -> {value * 2 + 1}'},
                {'value': 1, 'label': f'{value} -> 1'},
                {'value': 0, 'label': f'{value} -> 0'},
                {'value': 10_000_001, 'label': f'{value} -> 10000001'},
                {'value': -1, 'label': f'{value} -> -1'},
            ]
        )
        return out

    if isinstance(value, str):
        out.extend(
            [
                {'value': '', 'label': f'"{value}" -> ""'},
                {'value': 'ZZZZZ', 'label': f'"{value}" -> "ZZZZZ"'},
                {'value': 'Y', 'label': f'"{value}" -> "Y"'},
                {'value': 'N', 'label': f'"{value}" -> "N"'},
                {'value': '9999-12-31', 'label': f'"{value}" -> "9999-12-31"'},
                {'value': '1900-01-01', 'label': f'"{value}" -> "1900-01-01"'},
            ]
        )
        return out

    if isinstance(value, list):
        out.append({'value': [], 'label': 'array -> []'})
        out.append({'value': ['DUPLICATE', 'DUPLICATE'], 'label': 'array -> duplicated scalars'})

        first = value[0] if value else None
        if isinstance(first, dict):
            row = first

            # Flip every boolean flag on a copy of the first row -- this is
            # how the per-row rule flags (selfOccupiedInterestOverCap,
            # tdsOverClaimed, ...) fire.
            flipped = dict(row)
            for k, v in row.items():
                if isinstance(v, bool):
                    flipped[k] = not v
            out.append({'value': [flipped], 'label': 'first row -> all boolean flags flipped'})

            # Blank out every string and zero every number -- this is how
            # the "details are mandatory" rules fire.
            blanked = dict(row)
            for k, v in row.items():
                if isinstance(v, bool):
                    blanked[k] = True
                elif isinstance(v, str):
                    blanked[k] = ''
                elif isinstance(v, (int, float)):
                    blanked[k] = 0
            out.append({'value': [blanked], 'label': 'first row -> blanked'})

            # Two identical rows -- this is how the duplicate-PAN rules fire.
            out.append({'value': [row, dict(row)], 'label': 'first row duplicated'})

            # Both donation modes present, and a huge amount, for the 80G
            # row rules.
            inflated = dict(row)
            for k, v in row.items():
                if isinstance(v, bool):
                    inflated[k] = True
                elif isinstance(v, (int, float)):
                    inflated[k] = 10_000_001
            out.append({'value': [inflated], 'label': 'first row -> inflated'})
        else:
            out.append({'value': [*value, value[0] if value else None], 'label': 'first element duplicated'})
            out.append({'value': ['ZZZZZ'], 'label': 'array -> ["ZZZZZ"]'})
        return out

    if value is None:
        return [
            {'value': 1, 'label': 'null -> 1'},
            {'value': 'ZZZZZ', 'label': 'null -> "ZZZZZ"'},
            {'value': True, 'label': 'null -> true'},
            {'value': False, 'label': 'null -> false'},
        ]

    return out


def falsify(rule, facts, extra_variables=None):
    """Search for a fact perturbation that keeps `appliesWhen` true and makes
    the assertion false. Returns None when the assertion cannot be falsified
    through the facts it reads.

    `rule` is expected to expose `.appliesWhen` and `.assert_` attributes,
    matching the `itr.rules.registry.Rule` dataclass (whose `assert` field
    is named `assert_` because `assert` is a Python keyword).
    """
    extra_variables = extra_variables or []
    applies_when = rule.appliesWhen
    assertion_expr = rule.assert_

    vars_ = []
    seen = set()
    for v in [*referenced_variables(assertion_expr), *extra_variables]:
        if v in ('K', 'P') or v not in facts:
            continue
        if v not in seen:
            seen.add(v)
            vars_.append(v)

    literals = _literals_in(assertion_expr)
    const_arrays = _constant_arrays_in(assertion_expr, facts)
    scalar_peers = [facts[v] for v in vars_ if isinstance(facts[v], str) and facts[v] != '']

    def candidates_for_var(variable):
        value = facts[variable]
        candidate_list = _candidates_for(value)

        # Literals written into the expression: the uniqueness rules need
        # the dropdown value duplicated, the enum rules need the exact enum
        # token.
        for lit in literals:
            if isinstance(value, list):
                candidate_list.append({'value': [lit, lit], 'label': f'array -> ["{lit}","{lit}"]'})
                candidate_list.append({'value': [*value, lit, lit], 'label': f'array += "{lit}" twice'})
            elif isinstance(value, str):
                candidate_list.append({'value': lit, 'label': f'"{value}" -> "{lit}"'})

        # Constants the expression compares against, e.g. the TDS advisory
        # lists.
        if isinstance(value, list):
            for arr in const_arrays:
                candidate_list.append(
                    {'value': [arr[0]], 'label': f'array -> [{arr[0]!r}] (from constants)'}
                )
            # Other scalars in scope -- this is how "PAN must not appear in
            # the donee list" style rules are falsified.
            for peer in scalar_peers:
                candidate_list.append({'value': [*value, peer], 'label': f'array += "{peer}"'})
            # Zero every numeric column but keep the discriminator strings
            # intact.
            first = value[0] if value else None
            if isinstance(first, dict):
                row = first
                zeroed = dict(row)
                for k, v in row.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        zeroed[k] = 0
                candidate_list.append({'value': [zeroed], 'label': 'first row -> numeric columns zeroed'})

                # Retarget a discriminator column at each literal in the
                # expression -- this is how the per-block rules (Schedule
                # 80G tables A/B/C/D) fire.
                for lit in literals:
                    for k, v in row.items():
                        if not isinstance(v, str):
                            continue
                        retargeted = dict(zeroed)
                        retargeted[k] = lit
                        candidate_list.append(
                            {
                                'value': [retargeted],
                                'label': f'first row -> {k}="{lit}", numeric columns zeroed',
                            }
                        )
        return candidate_list

    for variable in vars_:
        for candidate in candidates_for_var(variable):
            mutated = {**facts, variable: candidate['value']}
            try:
                still_applies = evaluate_boolean(applies_when, mutated)
                assertion = evaluate_boolean(assertion_expr, mutated)
            except Exception:
                continue
            if still_applies and not assertion:
                return Falsification(variable, candidate['label'], mutated)

    # Some assertions need two facts moved together, e.g. A-335's "80CCD(1)
    # + 80CCD(1B) > 0".
    for a in vars_:
        for b in vars_:
            if a == b:
                continue
            for ca in candidates_for_var(a):
                for cb in candidates_for_var(b):
                    mutated = {**facts, a: ca['value'], b: cb['value']}
                    try:
                        if evaluate_boolean(applies_when, mutated) and not evaluate_boolean(assertion_expr, mutated):
                            return Falsification(f'{a} + {b}', f"{ca['label']}; {cb['label']}", mutated)
                    except Exception:
                        continue

    # PAYLOAD-scoped rules read through `P`; perturb inside the payload
    # object.
    if 'P' in facts and isinstance(facts.get('P'), dict):
        p = _falsify_payload(rule, facts)
        if p:
            return p
    return None


def _falsify_payload(rule, facts):
    """Walk the payload and try zeroing / inflating every numeric leaf."""
    applies_when = rule.appliesWhen
    assertion_expr = rule.assert_

    leaves = []

    def entries(node):
        if isinstance(node, dict):
            return node.items()
        if isinstance(node, list):
            return enumerate(node)
        return []

    def walk(node, path, depth):
        if depth > 6 or node is None or not isinstance(node, (dict, list)):
            return
        for k, v in entries(node):
            p = f'{path}.{k}' if path else str(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                leaves.append(p)
            elif isinstance(v, (dict, list)):
                walk(v, p, depth + 1)

    walk(facts.get('P'), '', 0)

    def _get(container, seg):
        return container[int(seg)] if isinstance(container, list) else container[seg]

    def _set(container, seg, value):
        if isinstance(container, list):
            container[int(seg)] = value
        else:
            container[seg] = value

    for leaf in leaves:
        for delta in (1, -1, 10_000_001):
            cloned = copy.deepcopy(facts['P'])
            segs = leaf.split('.')
            cur = cloned
            for seg in segs[:-1]:
                cur = _get(cur, seg)
            last = segs[-1]
            _set(cur, last, _get(cur, last) + delta)

            mutated = {**facts, 'P': cloned}
            try:
                if evaluate_boolean(applies_when, mutated) and not evaluate_boolean(assertion_expr, mutated):
                    sign = '+' if delta > 0 else ''
                    return Falsification(f'P.{leaf}', f'{sign}{delta}', mutated)
            except Exception:
                continue
    return None


def evaluate_values(values, facts):
    """Evaluate a rule's interpolation values so the harness can check the
    message."""
    out = {}
    for k, expr in values.items():
        try:
            out[k] = evaluate(expr, facts)
        except Exception:
            out[k] = None
    return out
