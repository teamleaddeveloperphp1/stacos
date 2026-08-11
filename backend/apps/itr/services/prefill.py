"""Form 16 / AIS pre-fill ingestion.

Ported from itr1-module/packages/core/src/services/prefill.ts.

IN SCOPE: the interface that accepts a structured payload from an upstream
service and populates the model. The upstream itself is a stub.

Pre-filled values are always merged into the model as ordinary user data --
they are never written into computed fields, and every derived figure is
recomputed afterwards (by the caller, via itr.engine.compute.compute).
"""

import copy

from apps.itr.util.num import n

_seq = 0


def _row_id(prefix):
    global _seq
    _seq += 1
    return f'{prefix}-pf-{_seq}'


def apply_prefill(model, payload, overwrite=False):
    """Merge a pre-fill payload into a model.

    `payload` shape (all keys optional except `source`/`fetchedAt`):
    `{source, fetchedAt, pan, personal: {firstName, middleName, lastName,
    dob, aadhaar, aadhaarLinkedToPan, email, mobile}, salary: [{employerName,
    tan, salary17_1, perquisites17_2, profitsInLieu17_3, tdsDeducted,
    incomeChargeableSalary}], otherSources: [{nature, amount}], tds2: [...],
    challans: [...], bankAccounts: [...]}`.

    When `overwrite` is False (the default) an existing non-empty value wins
    and the incoming value is reported as a conflict rather than applied.
    Returns `{'model': ..., 'applied': [...], 'conflicts': [...]}`.
    """
    m = copy.deepcopy(model)
    applied = []
    conflicts = []

    def set_scalar(path, current, incoming, assign):
        if incoming is None or incoming == '':
            return
        is_empty = current == '' or current is None or current == 0
        if not is_empty and current != incoming and not overwrite:
            conflicts.append({'path': path, 'existing': current, 'incoming': incoming})
            return
        assign()
        applied.append(path)

    p = payload.get('personal')
    if p:
        pi = m['personalInfo']
        set_scalar('personalInfo.firstName', pi['firstName'], p.get('firstName'),
                    lambda: pi.__setitem__('firstName', p['firstName']))
        set_scalar('personalInfo.middleName', pi['middleName'], p.get('middleName'),
                    lambda: pi.__setitem__('middleName', p['middleName']))
        set_scalar('personalInfo.lastName', pi['lastName'], p.get('lastName'),
                    lambda: pi.__setitem__('lastName', p['lastName']))
        set_scalar('personalInfo.dob', pi['dob'], p.get('dob'),
                    lambda: pi.__setitem__('dob', p['dob']))

        def _assign_aadhaar():
            pi['aadhaar'] = p['aadhaar']
            pi['aadhaarMatchesProfile'] = True

        set_scalar('personalInfo.aadhaar', pi['aadhaar'], p.get('aadhaar'), _assign_aadhaar)

        if p.get('aadhaarLinkedToPan') is not None:
            pi['aadhaarLinkedToPan'] = p['aadhaarLinkedToPan']
            applied.append('personalInfo.aadhaarLinkedToPan')

        contact = pi['contact']
        set_scalar('personalInfo.contact.primaryEmail', contact['primaryEmail'], p.get('email'),
                    lambda: contact.__setitem__('primaryEmail', p['email']))
        set_scalar('personalInfo.contact.primaryMobile', contact['primaryMobile'], p.get('mobile'),
                    lambda: contact.__setitem__('primaryMobile', p['mobile']))

    if payload.get('pan'):
        pan_upper = payload['pan'].upper()
        set_scalar('personalInfo.pan', m['personalInfo']['pan'], pan_upper,
                    lambda: m['personalInfo'].__setitem__('pan', pan_upper))

    salary = payload.get('salary') or []
    if salary:
        if m['income']['employers'] and not overwrite:
            conflicts.append({
                'path': 'income.employers',
                'existing': f"{len(m['income']['employers'])} employer block(s)",
                'incoming': f'{len(salary)} employer block(s)',
            })
        else:
            m['income']['employers'] = [
                {
                    'id': _row_id('emp'),
                    'employerName': e['employerName'],
                    'tan': e['tan'],
                    'employerCategory': m['personalInfo']['employerCategory'],
                    'salary17_1': n(e.get('salary17_1')),
                    'perquisites17_2': n(e.get('perquisites17_2')),
                    'profitsInLieu17_3': n(e.get('profitsInLieu17_3')),
                }
                for e in salary
            ]
            applied.append('income.employers')

            # Form 16 also gives Schedule TDS1.
            tds1 = [
                {
                    'id': _row_id('tds1'),
                    'tan': e['tan'],
                    'deductorName': e['employerName'],
                    'incomeChargeableSalary': n(e.get('incomeChargeableSalary', e.get('salary17_1'))),
                    'totalTaxDeducted': n(e.get('tdsDeducted')),
                }
                for e in salary if n(e.get('tdsDeducted')) > 0
            ]
            if tds1 and (not m['taxPaid']['tds1'] or overwrite):
                m['taxPaid']['tds1'] = tds1
                applied.append('taxPaid.tds1')
            elif tds1:
                conflicts.append({
                    'path': 'taxPaid.tds1',
                    'existing': len(m['taxPaid']['tds1']), 'incoming': len(tds1),
                })

    other_sources = payload.get('otherSources') or []
    if other_sources and (not m['income']['otherSources'] or overwrite):
        m['income']['otherSources'] = [
            {
                'id': _row_id('oth'),
                'nature': r['nature'],
                'otherNatureDescription': '',
                'amount': n(r.get('amount')),
                'dividendQuarterly': None,
            }
            for r in other_sources
        ]
        applied.append('income.otherSources')
    elif other_sources:
        conflicts.append({
            'path': 'income.otherSources',
            'existing': len(m['income']['otherSources']), 'incoming': len(other_sources),
        })

    tds2 = payload.get('tds2') or []
    if tds2 and (not m['taxPaid']['tds2'] or overwrite):
        m['taxPaid']['tds2'] = [
            {
                'id': _row_id('tds2'),
                'tanOrPan': r['tanOrPan'],
                'deductorName': r['deductorName'],
                'grossReceipt': n(r.get('grossReceipt')),
                'deductedYear': r.get('deductedYear', ''),
                'taxDeducted': n(r.get('taxDeducted')),
                'tdsClaimedThisYear': n(r.get('tdsClaimedThisYear')),
                'tdsSection': r.get('tdsSection', ''),
                'headOfIncome': '',
            }
            for r in tds2
        ]
        applied.append('taxPaid.tds2')

    challans = payload.get('challans') or []
    if challans and (not m['taxPaid']['challans'] or overwrite):
        m['taxPaid']['challans'] = [
            {
                'id': _row_id('chl'),
                'bsrCode': r['bsrCode'],
                'dateOfDeposit': r['dateOfDeposit'],
                'challanSerialNo': r['challanSerialNo'],
                'amount': n(r.get('amount')),
            }
            for r in challans
        ]
        applied.append('taxPaid.challans')

    bank_accounts = payload.get('bankAccounts') or []
    if bank_accounts and (not m['bankAccounts'] or overwrite):
        m['bankAccounts'] = [
            {
                'id': _row_id('bank'),
                'ifsc': b['ifsc'].upper(),
                'bankName': b['bankName'],
                'accountNumber': b['accountNumber'],
                'accountType': b['accountType'],
                'nominateForRefund': i == 0,
            }
            for i, b in enumerate(bank_accounts)
        ]
        applied.append('bankAccounts')

    return {'model': m, 'applied': applied, 'conflicts': conflicts}


class PrefillProvider:
    """Upstream stub. Replace with a real Form 16 / AIS client."""

    def fetch(self, pan, ay=None):
        raise NotImplementedError


class StubPrefillProvider(PrefillProvider):
    def __init__(self, fixtures=None):
        self.fixtures = fixtures or {}

    def fetch(self, pan, ay=None):
        return self.fixtures.get(pan.upper())
