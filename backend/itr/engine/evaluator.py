"""
Sandboxed expression evaluator for the rule registry.

ARCHITECTURE MANDATE 1: rules are data. Their `appliesWhen` / `assert` /
`values` expressions are evaluated here by simpleeval -- never by `eval`,
`exec`, or anything else with access to the host scope.

Ported from itr1-module/packages/core/src/engine/evaluator.ts. The grammar
used by the actual rule files is a subset of expr-eval's: `and` / `or` /
`not`, comparison operators, arithmetic, dotted attribute access, string/
number/boolean literals, and the helper functions registered below (no
ternary, no `in` operator, no array literals are used in practice -- verified
by scanning every appliesWhen/assert/values expression in the rule JSON).
JS-style lowercase `true`/`false` literals are supported via the names table.
"""

from types import SimpleNamespace

from simpleeval import EvalWithCompoundTypes, InvalidExpression


class ExpressionError(Exception):
    def __init__(self, expression, cause):
        self.expression = expression
        self.cause = cause
        super().__init__(f'Failed to evaluate expression "{expression}": {cause}')


def _to_list(v):
    if isinstance(v, (list, tuple)):
        return list(v)
    if v is None:
        return []
    return [v]


def _num(v):
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v if v == v and v not in (float('inf'), float('-inf')) else 0
    if v is None or v == '':
        return 0
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return 0


def _row_get(row, field):
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _in_list(x, arr):
    return x in _to_list(arr)


def _count_of(arr, x):
    return sum(1 for v in _to_list(arr) if v == x)


def _has_duplicates(arr):
    seen = set()
    for v in _to_list(arr):
        if v in ('', None):
            continue
        if v in seen:
            return True
        seen.add(v)
    return False


def _duplicates(arr):
    seen = set()
    dup = []
    dup_seen = set()
    for v in _to_list(arr):
        if v in ('', None):
            continue
        if v in seen and v not in dup_seen:
            dup.append(v)
            dup_seen.add(v)
        seen.add(v)
    return dup


def _intersects(arr, s):
    sset = set(_to_list(s))
    return any(v in sset for v in _to_list(arr))


def _count(arr):
    return len(_to_list(arr))


def _total(arr):
    return sum(_num(v) for v in _to_list(arr))


def _eq_tol(a, b, tol):
    return abs(_num(a) - _num(b)) <= _num(tol)


def _present(x):
    if x is None:
        return False
    if isinstance(x, str):
        return x.strip() != ''
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return x != 0
    if isinstance(x, (list, tuple)):
        return len(x) > 0
    return True


def _blank(x):
    if x is None:
        return True
    if isinstance(x, str):
        return x.strip() == ''
    if isinstance(x, (list, tuple)):
        return len(x) == 0
    return False


def _date_between(d, lo, hi):
    return isinstance(d, str) and d != '' and str(lo) <= d <= str(hi)


def _date_after(a, b):
    return isinstance(a, str) and a != '' and a > str(b)


def _date_before(a, b):
    return isinstance(a, str) and a != '' and a < str(b)


def _pluck(rows, field):
    return [_row_get(r, field) for r in _to_list(rows)]


def _where(rows, field, value):
    return [r for r in _to_list(rows) if _row_get(r, field) == value]


def _sum_of(rows, field):
    return sum(_num(_row_get(r, field)) for r in _to_list(rows))


def _any_eq(rows, field, value):
    return any(_row_get(r, field) == value for r in _to_list(rows))


def _any_gt(rows, field, value):
    return any(_num(_row_get(r, field)) > _num(value) for r in _to_list(rows))


def _is_subset_of(subset, superset):
    sset = set(_to_list(superset))
    return all(v in sset for v in _to_list(subset))


def _matches(x, regex):
    import re as _re
    try:
        return bool(_re.fullmatch(regex, str(x) if x is not None else ''))
    except _re.error:
        return False


def _path_segments(obj, dotted):
    cur = obj
    for seg in str(dotted).split('.'):
        if cur is None or not isinstance(cur, (dict, SimpleNamespace)):
            return None, False
        if isinstance(cur, dict):
            if seg not in cur:
                return None, False
            cur = cur[seg]
        else:
            if not hasattr(cur, seg):
                return None, False
            cur = getattr(cur, seg)
    return cur, True


def _path(obj, dotted):
    val, found = _path_segments(obj, dotted)
    return val if found else None


def _rows(obj, dotted):
    val, found = _path_segments(obj, dotted)
    if not found or val is None:
        return []
    return val if isinstance(val, (list, tuple)) else [val]


def _exists(obj, dotted):
    val, found = _path_segments(obj, dotted)
    return found and val is not None


HELPERS = {
    'inList': _in_list,
    'countOf': _count_of,
    'hasDuplicates': _has_duplicates,
    'duplicates': _duplicates,
    'intersects': _intersects,
    'count': _count,
    'total': _total,
    'abs': lambda x: abs(_num(x)),
    'min': lambda *xs: min(_num(x) for x in xs),
    'max': lambda *xs: max(_num(x) for x in xs),
    'floor': lambda x: int(_num(x) // 1),
    'round': lambda x: round(_num(x)),
    'eqTol': _eq_tol,
    'present': _present,
    'blank': _blank,
    'dateBetween': _date_between,
    'dateAfter': _date_after,
    'dateBefore': _date_before,
    'pluck': _pluck,
    'where': _where,
    'sumOf': _sum_of,
    'anyEq': _any_eq,
    'anyGt': _any_gt,
    'isSubsetOf': _is_subset_of,
    'upper': lambda x: str(x if x is not None else '').upper(),
    'len': lambda x: len(str(x if x is not None else '')),
    'matches': _matches,
    'num': _num,
    'path': _path,
    'rows': _rows,
    'exists': _exists,
}

# JS-style lowercase boolean literals used throughout the rule JSON.
_LITERAL_NAMES = {'true': True, 'false': False}

_compile_cache = {}


def _to_namespace(value):
    """Recursively convert dicts to attribute-accessible SimpleNamespace so
    `K.chapterVIA.s80U.disabilityAmount`-style dotted access works, matching
    expr-eval's native member-access semantics."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_namespace(v) for v in value]
    return value


def make_evaluator(facts):
    """Build a sandboxed evaluator bound to a fact bag (plain dict). Dict
    values are exposed as attribute-accessible namespaces so `K.a.b.c` style
    expressions work; list/dict-shaped facts passed to helper functions are
    also converted, since helpers use dict-style lookups internally and
    tolerate namespaces via `_row_get`."""
    names = dict(_LITERAL_NAMES)
    for key, value in facts.items():
        names[key] = _to_namespace(value)
    ev = EvalWithCompoundTypes(names=names, functions=dict(HELPERS))
    return ev


def evaluate(expression, facts):
    try:
        ev = make_evaluator(facts)
        return ev.eval(expression)
    except InvalidExpression as e:
        raise ExpressionError(expression, e) from e
    except Exception as e:  # noqa: BLE001 - mirror TS catch-all wrapping
        raise ExpressionError(expression, e) from e


def evaluate_boolean(expression, facts):
    return bool(evaluate(expression, facts))


def assert_compiles(expression):
    """Compile-check without a real fact bag, mirroring the TS registry
    loader's self-check. Uses an empty fact bag; simpleeval only raises at
    parse time for syntax errors, so undefined-name errors during this
    compile-only check are not treated as failures."""
    try:
        ev = EvalWithCompoundTypes(names=dict(_LITERAL_NAMES), functions=dict(HELPERS))
        ev.parse(expression)
    except SyntaxError as e:
        raise ExpressionError(expression, e) from e
