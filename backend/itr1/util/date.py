"""Date helpers. Everything is an ISO `YYYY-MM-DD` string in the model,
matching the CBDT schema's date pattern.

Ported from itr1-module/packages/core/src/util/date.ts.
"""

import re
from datetime import date, datetime

_ISO = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')

_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def is_iso_date(s):
    return isinstance(s, str) and bool(_ISO.match(s))


def is_before(a, b):
    """a < b"""
    if not is_iso_date(a) or not is_iso_date(b):
        return False
    return a < b


def is_after(a, b):
    """a > b"""
    if not is_iso_date(a) or not is_iso_date(b):
        return False
    return a > b


def is_between_inclusive(d, lo, hi):
    """lo <= d <= hi"""
    if not is_iso_date(d):
        return False
    return lo <= d <= hi


def age_on(dob, on):
    """Completed years between two dates (calendar age). Returns None on bad input."""
    if not is_iso_date(dob) or not is_iso_date(on):
        return None
    by, bm, bd = (int(x) for x in dob.split('-'))
    ry, rm, rd = (int(x) for x in on.split('-'))
    age = ry - by
    if rm < bm or (rm == bm and rd < bd):
        age -= 1
    return age


def months_or_part_from(from_, to):
    """Months (or part thereof) from `from_` up to and including `to`, as used
    by ss. 234A/234B. Any part of a month counts as a full month. Returns 0
    when `to` is not after `from_`."""
    if not is_iso_date(from_) or not is_iso_date(to):
        return 0
    if to <= from_:
        return 0
    fy, fm, fd = (int(x) for x in from_.split('-'))
    ty, tm, td = (int(x) for x in to.split('-'))
    months = (ty - fy) * 12 + (tm - fm)
    if td > fd:
        months += 1
    return max(months, 1)


def today_iso(now=None):
    now = now or date.today()
    return now.strftime('%Y-%m-%d')


def compact_timestamp(now=None):
    """`2026-08-07T13:20:45` -> `20260807132045` for the JSON filename."""
    now = now or datetime.now()
    return now.strftime('%Y%m%d%H%M%S')


def format_display_date(iso):
    """Display format used by the portal: 28-Dec-1986."""
    m = _ISO.match(iso or '')
    if not m:
        return iso or ''
    return f'{m.group(3)}-{_MONTHS[int(m.group(2)) - 1]}-{m.group(1)}'
