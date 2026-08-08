"""Fact bag for PAYLOAD-scoped rules.

Ported from itr1-module/packages/core/src/engine/payloadFacts.ts.

The CBDT rules of the form "total of column N should equal the sum of the
individual values" are only meaningful against the artifact that is actually
uploaded. Checking them against the model would be a tautology, because the
model stores rows and the totals are derived. So they are evaluated here,
against the generated JSON.

`P` is the ITR1 object. Aggregates that cannot be expressed as a single
path/rows call are pre-derived below.
"""

from itr1.engine.constants import CONSTANTS
from itr1.util.num import n


def _rows(obj, dotted):
    cur = obj
    for seg in dotted.split('.'):
        if not isinstance(cur, dict):
            return []
        cur = cur.get(seg)
    return cur if isinstance(cur, list) else []


def build_payload_facts(payload):
    """`payload` is the full `{ ITR: { ITR1: ... } }` document."""
    itr = (payload or {}).get('ITR') or {}
    p = itr.get('ITR1') or {}

    properties = _rows(p, 'ITR1_IncomeDeductions.PropertyDetails')

    # A-246 -- Schedule 24(b) across every property.
    sch24b_declared_total = 0
    sch24b_row_sum = 0
    for prop in properties:
        rent = prop.get('Rentdetails') or {}
        s24 = rent.get('Section24B') or {}
        sch24b_declared_total += n(s24.get('TotalInterestUs24B'))
        for r in s24.get('Section24BDtls') or []:
            sch24b_row_sum += n(r.get('InterestUs24B'))

    return {
        'P': p,
        'payload': payload,
        'sch24BDeclaredTotal': sch24b_declared_total,
        'sch24BRowSum': sch24b_row_sum,
        'propertyCount': len(properties),
        'K': CONSTANTS,
    }
