"""Response shaping for the ITR API. Deliberately thin wrappers, not DRF
ModelSerializers -- itr.services.return_service already returns plain
dicts of exactly what a caller renders; there is no ORM object here to
declare fields against. "Serializer" here means "shape this service dict
into the documented API response", not "map a Django model to JSON".

Money stays a plain int everywhere in these functions. Two documented
exceptions:
1. validation_report_to_dict()'s `values` field -- see _finding_to_api_shape's
   docstring.
2. get_computation()'s pass-through of itr.engine.compute.py's own output,
   which bakes formatted currency into two categories of narrative text this
   phase leaves untouched (ground rule 2): TraceBuilder narration under any
   `trace`-named key ("₹400,000 to ₹800,000 @ 5%"), and every Chapter VI-A
   section's `capReason` string built by compute.py's put() helper
   (compute.py:563), e.g. "14% of salary u/s 17(1) (A-216) = ₹46200". Both
   are prose, not amount fields -- every actual numeric field alongside them
   (including each trace line's own `amount`) is still a plain int.
   tests/itr/test_api_v1.py's money-shape test scopes around both.
"""

from itr.services.return_service import report_to_dict


def _finding_to_api_shape(f):
    """f is the dict shape itr.services.return_service.report_to_dict
    produces (dataclasses.asdict(Finding)) -- ruleId/camelCase, a `fields`
    tuple, a `values` dict.

    Deviation, stated per Phase 4 ground rule 5: the plan's sample error
    shape has fixed `value`/`allowed` keys. Finding.values is a
    rule-specific dict (e.g. A-1's is {'claimed': ..., 'limit': ...}, a
    different rule's might have three entries with different names) --
    there is no generic way to fold that into two fixed keys without
    guessing per rule, and itr/engine/validate.py (where `values` is built)
    is off-limits this phase. So `values` is passed through whole instead
    of forced into value/allowed. It is also, separately, the one place
    money leaks into this API as a formatted string rather than an int:
    validate.py's _format_value() bakes "₹1,50,000"-style text into
    `values` for message interpolation, before this shape even sees it --
    also off-limits to change this phase. Every other numeric field in
    this API (computation, get_return, regime-comparison) is a plain int;
    tests/itr/test_api_v1.py's money-shape test scopes around this one
    known exception explicitly rather than silently passing it."""
    fields = list(f.get('fields') or ())
    return {
        'rule_id': f['ruleId'],
        'category': f['category'],
        'severity': f['severity'],
        'screen': f['screen'],
        'tier': f['tier'],
        'field': fields[0] if fields else None,
        'fields': fields,
        'message': f['message'],
        'remediation': f['remediation'],
        'values': f['values'],
        'source': f['source'],
        'deepLink': f['deepLink'],
        'goto_url': f['goto_url'],
    }


def validation_report_to_dict(report):
    """`report` is either a raw itr.engine.validate.ValidationReport
    (dataclass instances, e.g. from GenerationBlockedError.result.validation)
    or the already-dict shape itr.services.return_service.report_to_dict
    produces (e.g. from run_validation()/confirm_screen()'s 'report' key)
    -- accept either so callers never need to know which one they hold."""
    d = report if isinstance(report, dict) else report_to_dict(report)
    return {
        'ok': d['ok'],
        'errors': [_finding_to_api_shape(f) for f in d['errors']],
        'advisories': [_finding_to_api_shape(f) for f in d['advisories']],
        'documentAdvisories': [_finding_to_api_shape(f) for f in d['documentAdvisories']],
        'ruleErrors': d['ruleErrors'],
        'tier': d['tier'],
        'screen': d['screen'],
        'ruleSetVersion': d['ruleSetVersion'],
        'constantsVersion': d['constantsVersion'],
        'rulesEvaluated': d['rulesEvaluated'],
        'rulesSkipped': d['rulesSkipped'],
        'evaluatedAt': d['evaluatedAt'],
    }


def return_summary_to_dict(tax_return):
    """One row of GET /api/v1/itr/returns/ -- deliberately lighter than
    get_return()'s full payload (no computed/model), matching what a list
    view needs vs a detail view."""
    return {
        'id': str(tax_return.pk),
        'pan': tax_return.pan,
        'ay': tax_return.data.get('ay', ''),
        'version': tax_return.version,
        'screen_status': tax_return.data.get('screenStatus', {}),
        'updated_at': tax_return.updated_at,
        'created_at': tax_return.created_at,
    }


def taxfiler_to_dict(filer):
    return {
        'id': str(filer.pk),
        'pan': filer.pan,
        'first_name': filer.first_name,
        'middle_name': filer.middle_name,
        'last_name': filer.last_name,
        'dob': filer.dob,
        'email': filer.email,
        'gender': filer.gender,
        'father_name': filer.father_name,
        'mobile_number': filer.mobile_number,
    }
