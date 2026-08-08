"""Numeric helpers. All money in the model is integer rupees.

Ported from itr1-module/packages/core/src/util/num.ts.
"""

import math
import re

_STRIP_RE = re.compile(r'[,\s₹]')


def n(v):
    if v is None or v == '':
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else 0
    x = _STRIP_RE.sub('', str(v))
    try:
        x = float(x)
    except ValueError:
        return 0
    return x if math.isfinite(x) else 0


def total(*xs):
    return sum(n(x) for x in xs)


def sum_by(rows, f):
    if not rows:
        return 0
    return sum(n(f(r)) for r in rows)


def pos(v):
    """Integer rupees, never negative."""
    return round(v) if v > 0 else 0


def clamp(v, lo, hi):
    return min(max(v, lo), hi)


def cap_at(v, limit):
    """Cap at `limit`; a None limit means "no cap"."""
    if limit is None:
        return v
    return min(v, limit)


def round_to_nearest(value, step):
    """s.288A / s.288B -- round to the nearest multiple of `step`.
    Statutory rule: fractions of the step of 5 or more round up, less than 5
    are ignored."""
    if not math.isfinite(value):
        return 0
    if step <= 1:
        return round(value)
    sign = -1 if value < 0 else 1
    absval = abs(value)
    rem = absval % step
    base = absval - rem
    return sign * (base + step if rem >= step / 2 else base)


def round_down_to_nearest(value, step):
    """Round DOWN to the nearest multiple of `step` (used for refunds)."""
    if not math.isfinite(value) or step <= 1:
        return math.floor(value)
    return math.floor(value / step) * step


def format_indian(value):
    """Indian digit grouping: 2,63,366 (not 263,366)."""
    sign = '-' if value < 0 else ''
    s = str(round(abs(value)))
    if len(s) <= 3:
        return sign + s
    last3 = s[-3:]
    rest = s[:-3]
    grouped = re.sub(r'(?<!^)(?=(\d{2})+$)', ',', rest)
    return f'{sign}{grouped},{last3}'


def format_rupees(value):
    return '₹' + format_indian(value)


def parse_amount_input(raw):
    """Strip everything a user might paste into an amount box."""
    cleaned = re.sub(r'[^0-9-]', '', raw)
    if cleaned in ('', '-'):
        return 0
    return int(float(cleaned))


def equals_within(a, b, tolerance=0):
    return abs(a - b) <= tolerance
