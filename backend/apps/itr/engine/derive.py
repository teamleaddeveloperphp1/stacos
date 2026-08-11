"""Derived Chapter VI-A section totals.

Several `deductions` fields are not genuine user input -- they must equal
the sum (or the single row's amount) of their own schedule, because tier-2
rules (A-241, A-201-300, A-301-339, ...) require an exact match between the
section total and its schedule. Deriving them here, in one place, means
every writer (the web form-processing path in itr/views.py, and any future
writer such as a REST API) reaches the same values, instead of each writer
re-implementing (and risking drifting from) the same sums.

Ported as a straight move from itr/views.py::_apply_deductions_forms --
same sums, same fields, no arithmetic changes.
"""


def derive_schedule_totals(model):
    """Mutates model['deductions'] in place, overwriting every derived
    section total from its own schedule. Call this once, after a writer has
    finished setting the schedule rows themselves (schedule80C,
    pensionContribution80CCC, schedule80DD, schedule80U, schedule80E/EE/
    EEA/EEB), so the totals it computes reflect the final schedule state."""
    d = model['deductions']

    d['s80C'] = sum(r['amount'] for r in d['schedule80C'])
    d['s80CCC'] = sum(r['amount'] for r in d['pensionContribution80CCC'])

    d['s80DD'] = d['schedule80DD']['amount']
    d['s80U'] = d['schedule80U']['amount']

    d['s80E'] = sum(r['interest'] for r in d['schedule80E'])
    d['s80EE'] = sum(r['interest'] for r in d['schedule80EE'])
    d['s80EEA'] = sum(r['interest'] for r in d['schedule80EEA'])
    d['s80EEB'] = sum(r['interest'] for r in d['schedule80EEB'])
