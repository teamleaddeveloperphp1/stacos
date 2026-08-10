"""Deep-link resolution for the Validation screen's "Go to field" links (§3.2,
§10.3). Every rule's `deepLink` is `SCREEN#anchor`; a screen typically groups
several related anchors under one fieldset, so this maps each of the ~80
anchors actually used across the rule registry onto the DOM `id` that exists
in that screen's template (see itr/templates/itr/*.html)."""

from django.urls import reverse

_SCREEN_URL_NAMES = {
    'PERSONAL_INFO': 'itr:personal_info',
    'GROSS_TOTAL_INCOME': 'itr:gross_total_income',
    'TOTAL_DEDUCTIONS': 'itr:total_deductions',
    'TAX_PAID': 'itr:tax_paid',
    'TAX_LIABILITY': 'itr:tax_liability',
    'TAX_SUMMARY': 'itr:tax_summary',
    'VALIDATION': 'itr:validation',
}

_ANCHOR_ALIASES = {
    'PERSONAL_INFO': {
        'lastName': 'profile', 'dateOfFormation': 'profile', 'aadhaar': 'profile',
        'employerCategory': 'profile', 'secondaryAddress': 'primaryAddress',
        'filingSection': 'filingSection', 'optOutOfNewRegime': 'filingSection',
        'a23Responses': 'filingSection', 'representativeAssessee': 'representativeAssessee',
        'bankDetails': 'bankDetails',
    },
    'GROSS_TOTAL_INCOME': {
        'b1': 'b1', 'b1i': 'b1', 'b1iii': 'b1', 'b1iv': 'b1', 'b1iva': 'b1',
        'b1ivb': 'b1', 'b1ivc': 'b1', 'b1v': 'b1', 'exemptAllowances': 'b1',
        'hraSchedule': 'b1', 'dividendQuarterly': 'b3',
        **{f'allowance-{x}': 'b1' for x in (
            '10(5)', '10(6)', '10(7)', '10(10)', '10(10A)', '10(10AA)',
            '10(10B)(i)', '10(10B)(ii)', '10(10C)', '10(10CC)', '10(13A)',
            '10(14)(i)', '10(14)(ii)', '10(14)(ii)(115BAC)', '10(17)', 'EIC',
        )},
        'b2': 'b2', 'b2i': 'b2', 'b2ii': 'b2', 'b2iii': 'b2', 'b2iv': 'b2',
        'b2v': 'b2', 'b2vii': 'b2', 'coOwnership': 'b2', 'schedule24b': 'b2',
        'propertyType': 'b2',
        'b3': 'b3',
        'exemptIncome': 'exemptIncome',
        'b4': 'b4', 'ltcg112A': 'b4',
    },
    'TOTAL_DEDUCTIONS': {
        'sec80C': 'sec80C', 'sec80CCC': 'sec80C', 'sec80CCD1': 'sec80C',
        'sec80CCD1B': 'sec80C', 'pran': 'sec80C',
        'sec80CCD2': 'sec80CCD2', 'sec80CCH': 'sec80CCD2',
        'sec80D': 'sec80D', 'sec80D-1a': 'sec80D', 'sec80D-1b': 'sec80D',
        'sec80D-2a': 'sec80D', 'sec80D-2b': 'sec80D',
        'sec80DD': 'sec80DD', 'sec80U': 'sec80DD',
        'sec80DDB': 'sec80DDB',
        'sec80E': 'sec80E', 'sec80EE': 'sec80E', 'sec80EEA': 'sec80E', 'sec80EEB': 'sec80E',
        'sec80G': 'sec80G',
        'sec80GG': 'sec80GG',
        'sec80GGA': 'sec80GGA',
        'sec80GGC': 'sec80GGC',
        'sec80TTA': 'sec80TTA', 'sec80TTB': 'sec80TTA',
        'totalDeductions': 'totalDeductions',
    },
    'TAX_PAID': {
        'scheduleTDS1': 'scheduleTDS1', 'scheduleTDS2': 'scheduleTDS2',
        'scheduleTDS3': 'scheduleTDS3', 'scheduleTCS': 'scheduleTCS',
        'scheduleIT': 'scheduleIT', 'totalTaxesPaid': 'totalTaxesPaid',
    },
    'TAX_LIABILITY': {
        'c2': 'c2', 'd2': 'c2', 'd3': 'c2', 'd5': 'c2',
        'd6': 'd6', 'd10a': 'd10a', 'd11': 'd11', 'totalInterestFee': 'd11',
    },
    'TAX_SUMMARY': {
        'payable': 'payable', 'refund': 'refund',
    },
}


def resolve_deep_link(return_id, deep_link):
    """`deep_link` is a rule's `SCREEN#anchor` string. Returns a URL path
    (`/returns/<id>/<screen>/#<domId>`) for the "Go to field" link, or None
    if the screen name isn't recognised."""
    if '#' not in deep_link:
        return None
    screen, anchor = deep_link.split('#', 1)
    url_name = _SCREEN_URL_NAMES.get(screen)
    if not url_name:
        return None
    dom_id = _ANCHOR_ALIASES.get(screen, {}).get(anchor, anchor)
    return f'{reverse(url_name, args=[return_id])}#{dom_id}'
