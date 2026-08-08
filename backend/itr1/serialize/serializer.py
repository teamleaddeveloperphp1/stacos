"""The ONE component that knows CBDT element names.

Ported from itr1-module/packages/core/src/serialize/serializer.ts.

ARCHITECTURE MANDATE 3: no UI component and no other engine module may
construct schema fragments. Everything upstream speaks the `ReturnModel`
plain dict (see itr1/model_blank.py).

Every element name below has been checked against
`itr1/data/ay2026-27/ITR-1_2026_Main_V1_1.json`. Where this module's naming or
arithmetic differs from the interpretive build prompt, the schema wins and the
discrepancy is recorded in docs/SCHEMA_MAPPING_NOTES.md (TS side).

`m` (the ReturnModel) and `c` (Computed) are plain nested Python dicts with
the same field names/nesting as their TS counterparts.
"""

import json

from itr1.engine.compute import compute as compute_return
from itr1.engine.constants import CONSTANTS as Constants
from itr1.util.date import compact_timestamp, today_iso
from itr1.util.num import n

from .schema_order import order_by_schema

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _amt(v):
    """Integer rupees, or None so the node is pruned."""
    x = n(v)
    return round(x)


def _req_amt(v):
    """A required integer -- always emitted, even at zero."""
    return round(n(v))


def _str(v):
    s = (v or '').strip() if isinstance(v, str) else (str(v).strip() if v is not None else '')
    return s if s != '' else None


def _upper(v):
    s = _str(v)
    return s.upper() if s else None


def _num_str(v):
    """Numeric string -> integer, for the schema's integer-typed phone/PIN fields."""
    s = ''.join(ch for ch in (v or '') if ch.isdigit()) if v is not None else ''
    return int(s) if s != '' else None


def _yn(v):
    return 'Y' if v else 'N'


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def _address_block(a, contact):
    return {
        'ResidenceNo': _str(a.get('flatDoorBuilding')),
        'ResidenceName': _str(a.get('premiseBuildingName')),
        'RoadOrStreet': _str(a.get('roadStreet')),
        'LocalityOrArea': _str(a.get('areaLocality')),
        'CityOrTownOrDistrict': _str(a.get('townCityDistrict')),
        'StateCode': _str(a.get('stateCode')),
        'CountryCode': _str(a.get('countryCode')),
        'PinCode': _num_str(a.get('pinCode')),
        'ZipCode': _str(a.get('zipCode')),
        'CountryCodeMobile': _num_str(contact.get('primaryMobileCountryCode')),
        'MobileNo': _num_str(contact.get('primaryMobile')),
        'CountryCodeMobileNoSec': _num_str(contact.get('secondaryMobileCountryCode')),
        'MobileNoSec': _num_str(contact.get('secondaryMobile')),
        'EmailAddress': _str(contact.get('primaryEmail')),
        'EmailAddressSec': _str(contact.get('secondaryEmail')),
    }


def _alternate_address_block(a):
    return {
        'ResidenceNo': _str(a.get('flatDoorBuilding')),
        'ResidenceName': _str(a.get('premiseBuildingName')),
        'RoadOrStreet': _str(a.get('roadStreet')),
        'LocalityOrArea': _str(a.get('areaLocality')),
        'CityOrTownOrDistrict': _str(a.get('townCityDistrict')),
        'StateCode': _str(a.get('stateCode')),
        'CountryCode': _str(a.get('countryCode')),
        'PinCode': _num_str(a.get('pinCode')),
        'ZipCode': _str(a.get('zipCode')),
    }


def _property_address(a):
    """AddressDetailWithZipCode -- used by PropertyDetails."""
    line = ', '.join(
        x for x in (a.get('flatDoorBuilding'), a.get('premiseBuildingName'), a.get('roadStreet'), a.get('areaLocality')) if x
    )
    addr = _str(line)
    return {
        'AddrDetail': addr[:50] if addr else None,
        'CityOrTownOrDistrict': (_str(a.get('townCityDistrict')) or '')[:50] or None,
        'StateCode': _str(a.get('stateCode')),
        'CountryCode': _str(a.get('countryCode')),
        'PinCode': _num_str(a.get('pinCode')),
        'ZipCode': _str(a.get('zipCode')),
    }


def _donee_address(a):
    """AddressDetail -- used by Schedule 80G / 80GGA donees. Max 200 chars."""
    line = ', '.join(
        x for x in (a.get('flatDoorBuilding'), a.get('premiseBuildingName'), a.get('roadStreet'), a.get('areaLocality')) if x
    )
    addr = _str(line)
    city = _str(a.get('townCityDistrict'))
    return {
        'AddrDetail': addr[:200] if addr else None,
        'CityOrTownOrDistrict': city[:50] if city else None,
        'StateCode': _str(a.get('stateCode')),
        'PinCode': _num_str(a.get('pinCode')),
    }


def _bank_block(b):
    return {
        'IFSCCode': _upper(b.get('ifsc')),
        'BankName': _str(b.get('bankName')),
        'BankAccountNo': _str(b.get('accountNumber')),
        'AccountType': _str(b.get('accountType')),
        # The schema declares UseForRefund as the STRING enum ["true","false"].
        'UseForRefund': 'true' if b.get('nominateForRefund') else 'false',
    }


def _loan_row(r, interest_key, extra=None):
    out = {
        'LoanTknFrom': _str(r.get('loanTakenFrom')),
        'BankOrInstnName': _str(r.get('lenderName')),
        'LoanAccNoOfBankOrInstnRefNo': _str(r.get('loanAccountNo')),
        'DateofLoan': _str(r.get('dateOfLoan')),
        'TotalLoanAmt': _req_amt(r.get('totalLoanAmount')),
        'LoanOutstndngAmt': _req_amt(r.get('loanOutstandingAmount')),
    }
    if extra:
        out.update(extra)
    out[interest_key] = _req_amt(r.get('interest'))
    return out


def _insurer_rows(b):
    insurers = b.get('insurers') or []
    if not insurers:
        return None
    return {
        'Sch80DInsDtls': [
            {
                'InsurerName': _str(i.get('insurerName')),
                'PolicyNo': _str(i.get('policyNo')),
                'HealthInsAmt': _req_amt(i.get('amount')),
            }
            for i in insurers
        ],
        'TotalPayments': sum(n(i.get('amount')) for i in insurers),
    }


def _donee_rows(rows, computed_rows):
    if not rows:
        return None
    eligible_by_id = {r['id']: r['eligibleDonation'] for r in computed_rows}
    out = []
    for r in rows:
        out.append(
            {
                'DoneeWithPanName': _str(r.get('name')),
                'DoneePAN': _upper(r.get('pan')),
                'ArnNbr': _str(r.get('arnNo')),
                'AddressDetail': _donee_address(r.get('address') or {}),
                'DonationAmtCash': _req_amt(r.get('donationCash')),
                'DonationAmtOtherMode': _req_amt(r.get('donationOtherMode')),
                'TransactionRefNum': _str(r.get('transactionRefNo')),
                'IFSCCode': _upper(r.get('ifsc')),
                'DonationAmt': _req_amt(n(r.get('donationCash')) + n(r.get('donationOtherMode'))),
                'EligibleDonationAmt': _req_amt(eligible_by_id.get(r.get('id'), 0)),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def serialize(m, opts=None):
    """Build the `{payload, json, filename, computed}` result for `m`.

    `opts` (all optional): `creationInfo` (partial override dict),
    `creationDate` (defaults to today), `computed` (a precomputed `Computed`
    dict, to avoid recomputation).
    """
    opts = opts or {}
    K = Constants
    c = opts.get('computed') if opts.get('computed') is not None else compute_return(m)
    ci = {**K['creationInfo'], **(opts.get('creationInfo') or {})}
    creation_date = opts.get('creationDate') or today_iso()

    inc = m['income']
    d = m['deductions']
    s = c['salary']

    # ---- Salary -------------------------------------------------------------
    allowance_rows = [
        {'SalNatureDesc': r['nature'], 'SalOthAmount': _req_amt(r['amount'])}
        for r in inc['exemptAllowances']
        if r.get('nature')
    ]

    allwnc_exempt_us10 = (
        {'AllwncExemptUs10Dtls': allowance_rows, 'TotalAllwncExemptUs10': _req_amt(s['totalExemptAllowances'])}
        if allowance_rows
        else None
    )

    # ---- House property -------------------------------------------------------
    property_details = None
    if inc['properties']:
        property_details = []
        for i, p in enumerate(inc['properties']):
            pc = c['houseProperty']['properties'][i]
            is_co_owned = p.get('coOwned') == 'YES'
            co_owners = None
            if is_co_owned and p.get('coOwners'):
                co_owners = [
                    {
                        'CoOwnersSNo': ci2 + 1,
                        'NameCoOwner': _str(co.get('name')),
                        'PAN_CoOwner': _upper(co.get('pan')),
                        'Aadhaar_CoOwner': _str(co.get('aadhaar')),
                        'PercentShareProperty': n(co.get('sharePercent')),
                    }
                    for ci2, co in enumerate(p['coOwners'])
                ]
            tenant_details = None
            if p.get('tenants'):
                tenant_details = [
                    {
                        'TenantSNo': ti + 1,
                        'NameofTenant': _str(t.get('name')),
                        'PANofTenant': _upper(t.get('pan')),
                        'AadhaarofTenant': _str(t.get('aadhaar')),
                        'PANTANofTenant': _upper(t.get('panOrTan')),
                    }
                    for ti, t in enumerate(p['tenants'])
                ]
            section24b = None
            if p.get('schedule24B'):
                section24b = {
                    'Section24BDtls': [
                        _loan_row({**r, 'interest': r['interestPaid']}, 'InterestUs24B') for r in p['schedule24B']
                    ],
                    'TotalInterestUs24B': _req_amt(pc['schedule24BTotal']),
                }
            property_details.append(
                {
                    'HPSNo': i + 1,
                    'AddressDetailWithZipCode': _property_address(p.get('address') or {}),
                    'PropertyOwner': _str(p.get('propertyOwner')),
                    'PropertyOwnerOther': _str(p.get('propertyOwnerOther')),
                    'PropCoOwnedFlg': 'YES' if is_co_owned else 'NO',
                    'AsseseeShareProperty': n(p.get('assesseeSharePercent')) if is_co_owned else 100,
                    'CoOwners': co_owners,
                    'ifLetOut': _str(p.get('propertyType')),
                    'TenantDetails': tenant_details,
                    'Rentdetails': {
                        'AnnualLetableValue': _req_amt(pc['grossRent']),
                        'RentNotRealized': _amt(pc['rentNotRealized']),
                        'LocalTaxes': _amt(pc['localTaxes']),
                        'TotalUnrealizedAndTax': _req_amt(pc['totalUnrealizedAndTax']),
                        'BalanceALV': _req_amt(pc['balanceAnnualValue']),
                        'AnnualOfPropOwned': _req_amt(pc['annualValueOfShare']),
                        'ThirtyPercentOfBalance': _req_amt(pc['thirtyPercent']),
                        'IntOnBorwCap': _req_amt(pc['interestAllowed']),
                        'Section24B': section24b,
                        'TotalDeduct': _req_amt(pc['totalDeduct']),
                        'ArrearsUnrealizedRentRcvd': _amt(pc['arrears']),
                        'IncomeOfHP': _req_amt(pc['incomeOfHP']),
                    },
                }
            )

    # ---- Other sources --------------------------------------------------------
    oth_src_rows = []
    for r in inc['otherSources']:
        if not r.get('nature'):
            continue
        dq = r.get('dividendQuarterly')
        dividend_inc = None
        if r['nature'] == 'DIV' and dq:
            dividend_inc = {
                'DateRange': {
                    'Upto15Of6': _req_amt(dq.get('Upto15Of6')),
                    'Upto15Of9': _req_amt(dq.get('Upto15Of9')),
                    'Up16Of9To15Of12': _req_amt(dq.get('Up16Of9To15Of12')),
                    'Up16Of12To15Of3': _req_amt(dq.get('Up16Of12To15Of3')),
                    'Up16Of3To31Of3': _req_amt(dq.get('Up16Of3To31Of3')),
                }
            }
        oth_src_rows.append(
            {
                'OthSrcNatureDesc': r['nature'],
                'OthSrcOthNatOfInc': _str(r.get('otherNatureDescription')) if r['nature'] == 'OTH' else None,
                'OthSrcOthAmount': _req_amt(r.get('amount')),
                'DividendInc': dividend_inc,
            }
        )

    # ---- Exempt income ---------------------------------------------------------
    exempt_rows = [
        {
            'Category': _str(r.get('category')),
            'SubCategory': _str(r.get('subCategory')),
            # V1.1 addition.
            'Description': _str(r.get('description')),
            'OthAmount': _req_amt(r.get('amount')),
        }
        for r in inc['exemptIncome']
        if r.get('subCategory') or n(r.get('amount')) > 0
    ]

    # ---- Chapter VI-A -----------------------------------------------------------
    def el(section):
        return _req_amt((c['deductions']['bySection'].get(section) or {}).get('eligible', 0))

    usr_deduct_und_chap_via = {
        'Section80C': _req_amt(d['s80C']),
        'Section80CCC': _req_amt(d['s80CCC']),
        'PensionContribution80CCC': (
            [
                {
                    'TypeofIdentifier': _str(r.get('typeOfIdentifier')),
                    'NameofIdentifier': _str(r.get('nameOfIdentifier')),
                    'Amount': _req_amt(r.get('amount')),
                }
                for r in d['pensionContribution80CCC']
            ]
            if d['pensionContribution80CCC']
            else None
        ),
        'Section80CCDEmployeeOrSE': _req_amt(d['s80CCD1']),
        'Section80CCD1B': _req_amt(d['s80CCD1B']),
        'Section80CCDEmployer': _req_amt(d['s80CCD2']),
        'PRANDtls': (
            [{'PRANNum': p} for p in d['pranNumbers'] if p] if [p for p in d['pranNumbers'] if p] else None
        ),
        'Section80D': _req_amt(d['s80D']),
        'Section80DD': _req_amt(d['s80DD']),
        'Section80DDBUsrType': _str(d['s80DDBUsrType']),
        'NameOfSpecDisease80DDB': _str(d['s80DDBDisease']),
        'Section80DDB': _req_amt(d['s80DDB']),
        'Section80E': _req_amt(d['s80E']),
        'Section80EE': _req_amt(d['s80EE']),
        'Section80EEA': _amt(d['s80EEA']),
        'Section80EEB': _amt(d['s80EEB']),
        'Section80G': _req_amt(d['s80G']),
        'Section80GG': _req_amt(d['s80GG']),
        'Form10BAAckNum': _str(d['form10BAAckNo']),
        'Section80GGA': _req_amt(d['s80GGA']),
        'Section80GGC': _req_amt(d['s80GGC']),
        'Section80U': _req_amt(d['s80U']),
        'Section80TTA': _req_amt(d['s80TTA']),
        'Section80TTB': _req_amt(d['s80TTB']),
        'AnyOthSec80CCH': _req_amt(d['s80CCH']),
        'TotalChapVIADeductions': _req_amt(sum(x['entered'] for x in c['deductions']['bySection'].values())),
    }

    deduct_und_chap_via = {
        'Section80C': el('80C'),
        'Section80CCC': el('80CCC'),
        'Section80CCDEmployeeOrSE': el('80CCD1'),
        'Section80CCD1B': el('80CCD1B'),
        'Section80CCDEmployer': el('80CCD2'),
        'Section80D': el('80D'),
        'Section80DD': el('80DD'),
        'Section80DDB': el('80DDB'),
        'Section80E': el('80E'),
        'Section80EE': el('80EE'),
        'Section80EEA': el('80EEA'),
        'Section80EEB': el('80EEB'),
        'Section80G': el('80G'),
        'Section80GG': el('80GG'),
        'Section80GGA': el('80GGA'),
        'Section80GGC': el('80GGC'),
        'Section80U': el('80U'),
        'Section80TTA': el('80TTA'),
        'Section80TTB': el('80TTB'),
        'AnyOthSec80CCH': el('80CCH'),
        'TotalChapVIADeductions': _req_amt(c['totalDeductions']),
    }

    # ---- Schedules ---------------------------------------------------------
    g = c['deductions']['schedule80G']
    total_80g_rows = (
        len(d['schedule80G']['don100Percent'])
        + len(d['schedule80G']['don50PercentNoApprReqd'])
        + len(d['schedule80G']['don100PercentApprReqd'])
        + len(d['schedule80G']['don50PercentApprReqd'])
    )

    schedule80g = None
    if total_80g_rows > 0:
        don100 = d['schedule80G']['don100Percent']
        don50_no_appr = d['schedule80G']['don50PercentNoApprReqd']
        don100_appr = d['schedule80G']['don100PercentApprReqd']
        don50_appr = d['schedule80G']['don50PercentApprReqd']
        schedule80g = {
            'Don100Percent': (
                {
                    'DoneeWithPan': _donee_rows(don100, g['blocks']['Don100Percent']['rows']),
                    'TotDon100PercentCash': _req_amt(g['blocks']['Don100Percent']['totalCash']),
                    'TotDon100PercentOtherMode': _req_amt(g['blocks']['Don100Percent']['totalOtherMode']),
                    'TotDon100Percent': _req_amt(g['blocks']['Don100Percent']['total']),
                    'TotEligibleDon100Percent': _req_amt(g['blocks']['Don100Percent']['totalEligible']),
                }
                if don100
                else None
            ),
            'Don50PercentNoApprReqd': (
                {
                    'DoneeWithPan': _donee_rows(don50_no_appr, g['blocks']['Don50PercentNoApprReqd']['rows']),
                    'TotDon50PercentNoApprReqdCash': _req_amt(g['blocks']['Don50PercentNoApprReqd']['totalCash']),
                    'TotDon50PercentNoApprReqdOtherMode': _req_amt(
                        g['blocks']['Don50PercentNoApprReqd']['totalOtherMode']
                    ),
                    'TotDon50PercentNoApprReqd': _req_amt(g['blocks']['Don50PercentNoApprReqd']['total']),
                    'TotEligibleDon50Percent': _req_amt(g['blocks']['Don50PercentNoApprReqd']['totalEligible']),
                }
                if don50_no_appr
                else None
            ),
            'Don100PercentApprReqd': (
                {
                    'DoneeWithPan': _donee_rows(don100_appr, g['blocks']['Don100PercentApprReqd']['rows']),
                    'TotDon100PercentApprReqdCash': _req_amt(g['blocks']['Don100PercentApprReqd']['totalCash']),
                    'TotDon100PercentApprReqdOtherMode': _req_amt(
                        g['blocks']['Don100PercentApprReqd']['totalOtherMode']
                    ),
                    'TotDon100PercentApprReqd': _req_amt(g['blocks']['Don100PercentApprReqd']['total']),
                    'TotEligibleDon100PercentApprReqd': _req_amt(
                        g['blocks']['Don100PercentApprReqd']['totalEligible']
                    ),
                }
                if don100_appr
                else None
            ),
            'Don50PercentApprReqd': (
                {
                    'DoneeWithPan': _donee_rows(don50_appr, g['blocks']['Don50PercentApprReqd']['rows']),
                    'TotDon50PercentApprReqdCash': _req_amt(g['blocks']['Don50PercentApprReqd']['totalCash']),
                    'TotDon50PercentApprReqdOtherMode': _req_amt(
                        g['blocks']['Don50PercentApprReqd']['totalOtherMode']
                    ),
                    'TotDon50PercentApprReqd': _req_amt(g['blocks']['Don50PercentApprReqd']['total']),
                    'TotEligibleDon50PercentApprReqd': _req_amt(
                        g['blocks']['Don50PercentApprReqd']['totalEligible']
                    ),
                }
                if don50_appr
                else None
            ),
            'TotalDonationsUs80GCash': _req_amt(g['totalCash']),
            'TotalDonationsUs80GOtherMode': _req_amt(g['totalOtherMode']),
            'TotalDonationsUs80G': _req_amt(g['total']),
            'TotalEligibleDonationsUs80G': _req_amt(g['totalEligible']),
        }

    gga = c['deductions']['schedule80GGA']
    schedule80gga = None
    if d['schedule80GGA']:
        gga_by_id = {x['id']: x['eligible'] for x in gga['perRow']}
        schedule80gga = {
            'DonationDtlsSciRsrchRuralDev': [
                {
                    'RelevantClauseUndrDedClaimed': _str(r.get('relevantClause')),
                    'NameOfDonee': _str(r.get('name')),
                    'AddressDetail': _donee_address(r.get('address') or {}),
                    'DoneePAN': _upper(r.get('pan')),
                    'DonationAmtCash': _req_amt(r.get('donationCash')),
                    'DonationAmtOtherMode': _req_amt(r.get('donationOtherMode')),
                    'DonationAmt': _req_amt(n(r.get('donationCash')) + n(r.get('donationOtherMode'))),
                    'EligibleDonationAmt': _req_amt(gga_by_id.get(r.get('id'), 0)),
                }
                for r in d['schedule80GGA']
            ],
            'TotalDonationAmtCash80GGA': _req_amt(gga['totalCash']),
            'TotalDonationAmtOtherMode80GGA': _req_amt(gga['totalOtherMode']),
            'TotalDonationsUs80GGA': _req_amt(gga['total']),
            'TotalEligibleDonationAmt80GGA': _req_amt(gga['eligible']),
        }

    ggc = c['deductions']['schedule80GGC']
    schedule80ggc = None
    if d['schedule80GGC']:
        ggc_by_id = {x['id']: x['eligible'] for x in ggc['perRow']}
        schedule80ggc = {
            'Schedule80GGCDetails': [
                {
                    'DonationDate': _str(r.get('donationDate')),
                    'DonationAmtCash': _req_amt(r.get('donationCash')),
                    'DonationAmtOtherMode': _req_amt(r.get('donationOtherMode')),
                    'TransactionRefNum': _str(r.get('transactionRefNo')),
                    'IFSCCode': _upper(r.get('ifsc')),
                    'DonationAmt': _req_amt(n(r.get('donationCash')) + n(r.get('donationOtherMode'))),
                    'EligibleDonationAmt': _req_amt(ggc_by_id.get(r.get('id'), 0)),
                    'PoliticalPartyName': _str(r.get('politicalPartyName')),
                    'PoliticalPartyPAN': _upper(r.get('politicalPartyPan')),
                }
                for r in d['schedule80GGC']
            ],
            'TotalDonationAmtCash80GGC': _req_amt(ggc['totalCash']),
            'TotalDonationAmtOtherMode80GGC': _req_amt(ggc['totalOtherMode']),
            'TotalDonationsUs80GGC': _req_amt(ggc['total']),
            'TotalEligibleDonationAmt80GGC': _req_amt(ggc['eligible']),
        }

    s80d = d['schedule80D']
    c80d = c['deductions']['schedule80D']
    schedule80d = None
    if s80d['selfFamilySeniorFlag'] or s80d['parentsSeniorFlag']:
        schedule80d = {
            'Sec80DSelfFamSrCtznHealth': {
                'SeniorCitizenFlag': _str(s80d['selfFamilySeniorFlag']),
                'SelfAndFamily': _amt(c80d['selfFamily']['deduction']),
                'HealthInsPremSlfFam': _amt(s80d['selfFamily']['healthInsurancePremium']),
                'Sec80DSelfFamHIDtls': _insurer_rows(s80d['selfFamily']),
                'PrevHlthChckUpSlfFam': _amt(c80d['selfFamily']['preventiveHealthCheckup']),
                'SelfAndFamilySeniorCitizen': _amt(c80d['selfFamilySenior']['deduction']),
                'HlthInsPremSlfFamSrCtzn': _amt(s80d['selfFamilySenior']['healthInsurancePremium']),
                'Sec80DSelfFamSrCtznHIDtls': _insurer_rows(s80d['selfFamilySenior']),
                'PrevHlthChckUpSlfFamSrCtzn': _amt(c80d['selfFamilySenior']['preventiveHealthCheckup']),
                'MedicalExpSlfFamSrCtzn': _amt(c80d['selfFamilySenior']['medicalExpenditure']),
                'ParentsSeniorCitizenFlag': _str(s80d['parentsSeniorFlag']),
                'Parents': _amt(c80d['parents']['deduction']),
                'HlthInsPremParents': _amt(s80d['parents']['healthInsurancePremium']),
                'Sec80DParentsHIDtls': _insurer_rows(s80d['parents']),
                'PrevHlthChckUpParents': _amt(c80d['parents']['preventiveHealthCheckup']),
                'ParentsSeniorCitizen': _amt(c80d['parentsSenior']['deduction']),
                'HlthInsPremParentsSrCtzn': _amt(s80d['parentsSenior']['healthInsurancePremium']),
                'Sec80DParentsSrCtznHIDtls': _insurer_rows(s80d['parentsSenior']),
                'PrevHlthChckUpParentsSrCtzn': _amt(c80d['parentsSenior']['preventiveHealthCheckup']),
                'MedicalExpParentsSrCtzn': _amt(c80d['parentsSenior']['medicalExpenditure']),
                'EligibleAmountOfDedn': _req_amt(c80d['eligibleAmountOfDeduction']),
            },
        }

    schedule80dd = None
    if d['schedule80DD']['natureOfDisability'] and n(d['s80DD']) > 0:
        schedule80dd = {
            'NatureOfDisability': _str(d['schedule80DD']['natureOfDisability']),
            'TypeOfDisability': _str(d['schedule80DD']['typeOfDisability']),
            'DeductionAmount': _req_amt(d['schedule80DD']['amount']),
            'DependentType': _str(d['schedule80DD']['dependentType']),
            'DependentPan': _upper(d['schedule80DD']['dependentPan']),
            'DependentAadhaar': _str(d['schedule80DD']['dependentAadhaar']),
            'Form10IAAckNum': _str(d['schedule80DD']['form10IAAckNo']),
            'UDIDNum': _str(d['schedule80DD']['udidNo']),
        }

    schedule80u = None
    if d['schedule80U']['natureOfDisability'] and n(d['s80U']) > 0:
        schedule80u = {
            'NatureOfDisability': _str(d['schedule80U']['natureOfDisability']),
            'TypeOfDisability': _str(d['schedule80U']['typeOfDisability']),
            'DeductionAmount': _req_amt(d['schedule80U']['amount']),
            'Form10IAAckNum': _str(d['schedule80U']['form10IAAckNo']),
            'UDIDNum': _str(d['schedule80U']['udidNo']),
        }

    schedule80e = (
        {
            'Schedule80EDtls': [_loan_row(r, 'Interest80E') for r in d['schedule80E']],
            'TotalInterest80E': _req_amt(c['deductions']['schedule80ETotal']),
        }
        if d['schedule80E']
        else None
    )
    schedule80ee = (
        {
            'Schedule80EEDtls': [_loan_row(r, 'Interest80EE') for r in d['schedule80EE']],
            'TotalInterest80EE': _req_amt(c['deductions']['schedule80EETotal']),
        }
        if d['schedule80EE']
        else None
    )
    schedule80eea = (
        {
            'PropStmpDtyVal': _req_amt(d['stampDutyValue80EEA']),
            'Schedule80EEADtls': [_loan_row(r, 'Interest80EEA') for r in d['schedule80EEA']],
            'TotalInterest80EEA': _req_amt(c['deductions']['schedule80EEATotal']),
        }
        if d['schedule80EEA']
        else None
    )
    schedule80eeb = (
        {
            'Schedule80EEBDtls': [
                _loan_row(r, 'Interest80EEB', {'VehicleRegNo': _str(r.get('vehicleRegNo'))}) for r in d['schedule80EEB']
            ],
            'TotalInterest80EEB': _req_amt(c['deductions']['schedule80EEBTotal']),
        }
        if d['schedule80EEB']
        else None
    )
    schedule80c = (
        {
            'Schedule80CDtls': [
                {'Amount': _req_amt(r.get('amount')), 'IdentificationNo': _str(r.get('identificationNo'))}
                for r in d['schedule80C']
            ],
            'TotalAmt': _req_amt(c['deductions']['schedule80CTotal']),
        }
        if d['schedule80C']
        else None
    )

    h = inc['hra10_13A']
    schedule_ea10_13a = None
    if c['regime'] == 'OLD' and (n(h['actualHraReceived']) > 0 or n(h['actualRentPaid']) > 0):
        schedule_ea10_13a = {
            'Placeofwork': _str(h['placeOfWork']),
            'ActlHRARecv': _req_amt(h['actualHraReceived']),
            'ActlRentPaid': _req_amt(h['actualRentPaid']),
            'DtlsSalUsSec171': _req_amt(h['salary17_1']),
            'BasicSalary': _req_amt(h['basicSalary']),
            'DearnessAllwnc': _amt(h['dearnessAllowance']),
            'ActlRentPaid10Per': _req_amt(c['hra']['rentPaidLess10PercentOfSalary']),
            'Sal40Or50Per': _req_amt(c['hra']['salary40Or50Percent']),
            'EligbleExmpAllwncUs13A': _req_amt(c['hra']['eligibleExemption']),
        }

    # ---- Tax paid schedules ----------------------------------------------------
    tds_on_salaries = None
    if m['taxPaid']['tds1']:
        tds_on_salaries = {
            'TDSonSalary': [
                {
                    'EmployerOrDeductorOrCollectDetl': {
                        'TAN': _upper(r.get('tan')),
                        'EmployerOrDeductorOrCollecterName': _str(r.get('deductorName')),
                    },
                    'IncChrgSal': _req_amt(r.get('incomeChargeableSalary')),
                    'TotalTDSSal': _req_amt(r.get('totalTaxDeducted')),
                }
                for r in m['taxPaid']['tds1']
            ],
            'TotalTDSonSalaries': _req_amt(c['taxesPaid']['tds1']),
        }

    tds_on_oth_than_sals = None
    if m['taxPaid']['tds2']:
        tds_on_oth_than_sals = {
            'TDSonOthThanSal': [
                {
                    'EmployerOrDeductorOrCollectDetl': {
                        'TAN': _upper(r.get('tanOrPan')),
                        'EmployerOrDeductorOrCollecterName': _str(r.get('deductorName')),
                    },
                    'TDSSection': _str(r.get('tdsSection')),
                    'AmtForTaxDeduct': _req_amt(r.get('grossReceipt')),
                    'DeductedYr': _str(r.get('deductedYear')),
                    'TotTDSOnAmtPaid': _req_amt(r.get('taxDeducted')),
                    'ClaimOutOfTotTDSOnAmtPaid': _req_amt(r.get('tdsClaimedThisYear')),
                }
                for r in m['taxPaid']['tds2']
            ],
            'TotalTDSonOthThanSals': _req_amt(c['taxesPaid']['tds2']),
        }

    schedule_tds3_dtls = None
    if m['taxPaid']['tds3']:
        schedule_tds3_dtls = {
            'TDS3Details': [
                {
                    'PANofTenant': _upper(r.get('panOfTenant')),
                    'AadhaarofTenant': _str(r.get('aadhaarOfTenant')),
                    'TDSSection': _str(r.get('tdsSection')),
                    'NameOfTenant': _str(r.get('nameOfTenant')),
                    'GrsRcptToTaxDeduct': _req_amt(r.get('grossReceipt')),
                    'DeductedYr': _str(r.get('deductedYear')),
                    'TDSDeducted': _req_amt(r.get('taxDeducted')),
                    'TDSClaimed': _req_amt(r.get('tdsClaimedThisYear')),
                }
                for r in m['taxPaid']['tds3']
            ],
            'TotalTDS3Details': _req_amt(c['taxesPaid']['tds3']),
        }

    schedule_tcs = None
    if m['taxPaid']['tcs']:
        schedule_tcs = {
            'TCS': [
                {
                    'EmployerOrDeductorOrCollectDetl': {
                        'TAN': _upper(r.get('tan')),
                        'EmployerOrDeductorOrCollecterName': _str(r.get('collectorName')),
                    },
                    'AmtTaxCollected': _req_amt(r.get('taxCollected')),
                    'CollectedYr': _str(r.get('collectedYear')),
                    'TotalTCS': _req_amt(r.get('totalTcs')),
                    'AmtTCSClaimedThisYear': _req_amt(r.get('tcsClaimedThisYear')),
                }
                for r in m['taxPaid']['tcs']
            ],
            'TotalSchTCS': _req_amt(c['taxesPaid']['tcs']),
        }

    tax_payments = None
    if m['taxPaid']['challans']:
        tax_payments = {
            'TaxPayment': [
                {
                    'BSRCode': _upper(r.get('bsrCode')),
                    'DateDep': _str(r.get('dateOfDeposit')),
                    'SrlNoOfChaln': _num_str(r.get('challanSerialNo')),
                    'Amt': _req_amt(r.get('amount')),
                }
                for r in m['taxPaid']['challans']
            ],
            'TotalTaxPayments': _req_amt(c['taxesPaid']['advanceTax'] + c['taxesPaid']['selfAssessmentTax']),
        }

    ltcg112a = None
    if c['ltcg112A'] > 0 or c['ltcg112ASubRows']['sale'] > 0:
        ltcg112a = {
            'TotSaleCnsdrn': _req_amt(c['ltcg112ASubRows']['sale']),
            'TotCstAcqisn': _req_amt(c['ltcg112ASubRows']['cost']),
            'LongCap112A': _req_amt(c['ltcg112A']),
        }

    # ---- Filing status -----------------------------------------------------
    sp = m['filingStatus']['seventhProviso']
    filing_status = {
        'ReturnFileSec': m['filingStatus']['returnFileSec'],
        'OptOutNewTaxRegime': m['filingStatus']['optOutOfNewRegime'],
        'SeventhProvisio139': m['filingStatus']['seventhProviso139'],
        'IncrExpAggAmt2LkTrvFrgnCntryFlg': (
            sp['travelExpenseAbove2Lakh'] if m['filingStatus']['seventhProviso139'] == 'Y' else None
        ),
        'AmtSeventhProvisio139ii': (
            _amt(sp['travelExpenseAmount']) if sp['travelExpenseAbove2Lakh'] == 'Y' else None
        ),
        'IncrExpAggAmt1LkElctrctyPrYrFlg': (
            sp['electricityAbove1Lakh'] if m['filingStatus']['seventhProviso139'] == 'Y' else None
        ),
        'AmtSeventhProvisio139iii': (
            _amt(sp['electricityAmount']) if sp['electricityAbove1Lakh'] == 'Y' else None
        ),
        'clauseiv7provisio139i': (
            sp['clauseIvApplies'] if m['filingStatus']['seventhProviso139'] == 'Y' else None
        ),
        'clauseiv7provisio139iDtls': (
            [
                {'clauseiv7provisio139iNature': x['nature'], 'clauseiv7provisio139iAmount': _req_amt(x['amount'])}
                for x in sp['clauseIvDetails']
            ]
            if sp['clauseIvDetails']
            else None
        ),
        'ReceiptNo': _str(m['filingStatus']['origReturnAckNo']),
        'NoticeNo': _str(m['filingStatus']['noticeNo']),
        'OrigRetFiledDate': _str(m['filingStatus']['origReturnFiledDate']),
        'NoticeDateUnderSec': _str(m['filingStatus']['noticeDate']),
        'AsseseeRepFlg': m['filingStatus']['representativeAssesseeFlag'],
        'AssesseeRep': (
            {
                'RepName': _str(m['filingStatus']['representativeAssessee'].get('name')),
                'RepEmailID': _str(m['filingStatus']['representativeAssessee'].get('email')),
                'CountryCodeRepMobileNo': _num_str(m['filingStatus']['representativeAssessee'].get('mobileCountryCode')),
                'RepMobileNo': _num_str(m['filingStatus']['representativeAssessee'].get('mobile')),
            }
            if m['filingStatus']['representativeAssesseeFlag'] == 'Y' and m['filingStatus']['representativeAssessee']
            else None
        ),
        'ItrFilingDueDate': K['dueDates']['us139_1'],
    }

    # ---- Assemble ------------------------------------------------------------
    itr1 = {
        'CreationInfo': {
            'SWVersionNo': ci['swVersionNo'],
            'SWCreatedBy': ci['swCreatedBy'],
            'JSONCreatedBy': ci['jsonCreatedBy'],
            'JSONCreationDate': creation_date,
            'IntermediaryCity': ci['intermediaryCity'],
            'Digest': ci['digest'],
        },
        'Form_ITR1': {
            'FormName': K['formMeta']['formName'],
            'Description': K['formMeta']['description'],
            'AssessmentYear': K['formMeta']['assessmentYear'],
            'SchemaVer': K['formMeta']['schemaVer'],
            'FormVer': K['formMeta']['formVer'],
        },
        'PersonalInfo': {
            'AssesseeName': {
                'FirstName': _str(m['personalInfo']['firstName']),
                'MiddleName': _str(m['personalInfo']['middleName']),
                'SurNameOrOrgName': _str(m['personalInfo']['lastName']),
            },
            'PAN': _upper(m['personalInfo']['pan']),
            'Address': _address_block(m['personalInfo']['primaryAddress'], m['personalInfo']['contact']),
            'SecondaryAdd': m['personalInfo']['secondaryAddressSameAsPrimary'],
            'AlternateAddress': (
                _alternate_address_block(m['personalInfo']['secondaryAddress'])
                if m['personalInfo']['secondaryAddressSameAsPrimary'] == 'N'
                else None
            ),
            'DOB': _str(m['personalInfo']['dob']),
            'EmployerCategory': _str(m['personalInfo']['employerCategory']),
            'AadhaarCardNo': _str(m['personalInfo']['aadhaar']),
        },
        'FilingStatus': filing_status,
        'ITR1_IncomeDeductions': {
            'GrossSalary': _req_amt(s['grossSalary']),
            'Salary': _amt(s['salary17_1']),
            'PerquisitesValue': _amt(s['perquisites17_2']),
            'ProfitsInSalary': _amt(s['profitsInLieu17_3']),
            'AllwncExemptUs10': allwnc_exempt_us10,
            'NetSalary': _req_amt(s['netSalary']),
            'DeductionUs16': _req_amt(s['deductionUs16']),
            'DeductionUs16ia': _amt(s['standardDeduction16ia']),
            'EntertainmentAlw16ii': _amt(s['entertainmentAllowance16ii']),
            'ProfessionalTaxUs16iii': _amt(s['professionalTax16iii']),
            'IncomeFromSal': _req_amt(s['incomeFromSalary']),
            'PropertyDetails': property_details,
            'TotalIncomeChargeableUnHP': _amt(c['houseProperty']['incomeForGti']),
            'IncomeOthSrc': _req_amt(c['otherSources']['netIncomeOthSrc']),
            'OthersInc': {'OthersIncDtlsOthSrc': oth_src_rows} if oth_src_rows else None,
            'DeductionUs57iia': _amt(c['otherSources']['deduction57iia']),
            'GrossTotIncome': _req_amt(c['grossTotalIncome']),
            'GrossTotIncomeIncLTCG112A': _req_amt(c['grossTotalIncomeInclLtcg']),
            'UsrDeductUndChapVIA': usr_deduct_und_chap_via,
            'DeductUndChapVIA': deduct_und_chap_via,
            'TotalIncome': _req_amt(c['totalIncome']),
            'ExemptIncAgriOthUs10': (
                {
                    'ExemptIncAgriOthUs10Dtls': exempt_rows,
                    'ExemptIncAgriOthUs10Total': _req_amt(c['exemptIncomeTotal']),
                }
                if exempt_rows
                else None
            ),
        },
        'ITR1_TaxComputation': {
            'TotalTaxPayable': _req_amt(c['tax']['taxPayableOnTotalIncome']),
            'Rebate87A': _req_amt(c['tax']['rebate87A']),
            'TaxPayableOnRebate': _req_amt(c['tax']['taxPayableAfterRebate']),
            'EducationCess': _req_amt(c['tax']['educationCess']),
            'GrossTaxLiability': _req_amt(c['tax']['totalTaxAndCess']),
            'Section89': _req_amt(c['tax']['relief89']),
            'NetTaxLiability': _req_amt(c['tax']['balanceTaxAfterRelief']),
            'TotalIntrstPay': _req_amt(c['interest']['total']),
            'IntrstPay': {
                'IntrstPayUs234A': _req_amt(c['interest']['interest234A']),
                'IntrstPayUs234B': _req_amt(c['interest']['interest234B']),
                'IntrstPayUs234C': _req_amt(c['interest']['interest234C']),
                'LateFilingFee234F': _req_amt(c['interest']['fee234F']),
                'FeeFurnish234I': _amt(c['interest']['fee234I']),
            },
            'TotTaxPlusIntrstPay': _req_amt(c['totalTaxFeeAndInterest']),
        },
        'TaxPaid': {
            'TaxesPaid': {
                'AdvanceTax': _req_amt(c['taxesPaid']['advanceTax']),
                'TDS': _req_amt(c['taxesPaid']['totalTds']),
                'TCS': _req_amt(c['taxesPaid']['tcs']),
                'SelfAssessmentTax': _req_amt(c['taxesPaid']['selfAssessmentTax']),
                'TotalTaxesPaid': _req_amt(c['taxesPaid']['total']),
            },
            'BalTaxPayable': _req_amt(c['balanceTaxPayable']),
        },
        'Refund': {
            'RefundDue': _req_amt(c['refundDue']),
            'BankAccountDtls': (
                {'AddtnlBankDetails': [_bank_block(b) for b in m['bankAccounts']]} if m['bankAccounts'] else {}
            ),
        },
        'Schedule80G': schedule80g,
        'Schedule80GGA': schedule80gga,
        'Schedule80GGC': schedule80ggc,
        'Schedule80D': schedule80d,
        'Schedule80DD': schedule80dd,
        'Schedule80U': schedule80u,
        'Schedule80E': schedule80e,
        'Schedule80EE': schedule80ee,
        'Schedule80EEA': schedule80eea,
        'Schedule80EEB': schedule80eeb,
        'Schedule80C': schedule80c,
        'ScheduleEA10_13A': schedule_ea10_13a,
        'TDSonSalaries': tds_on_salaries,
        'TDSonOthThanSals': tds_on_oth_than_sals,
        'ScheduleTDS3Dtls': schedule_tds3_dtls,
        'ScheduleTCS': schedule_tcs,
        'TaxPayments': tax_payments,
        'LTCG112A': ltcg112a,
        'Verification': {
            'Declaration': {
                'AssesseeVerName': _str(m['verification']['assesseeVerName']),
                'FatherName': _str(m['verification']['fatherName']),
                'AssesseeVerPAN': _upper(m['verification']['assesseeVerPan']),
            },
            'Capacity': _str(m['verification']['capacity']),
            'Place': _str(m['verification']['place']),
        },
        'TaxReturnPreparer': (
            {
                'IdentificationNoOfTRP': _str(m['taxReturnPreparer']['identificationNo']),
                'NameOfTRP': _str(m['taxReturnPreparer']['name']),
                'ReImbFrmGov': _amt(m['taxReturnPreparer']['reimbursementFromGovt']),
            }
            if m['taxReturnPreparer']['enabled']
            else None
        ),
    }

    payload = order_by_schema({'ITR': {'ITR1': itr1}})

    # NON-NEGOTIABLE 7 (idempotence): a stable, sorted-by-schema-order document
    # serialised with fixed formatting. Only JSONCreationDate can differ between
    # two generations from the same model.
    json_str = json.dumps(payload, indent=2, ensure_ascii=False)

    return {
        'payload': payload,
        'json': json_str,
        'filename': build_filename(m, opts.get('creationDate')),
        'computed': c,
    }


def build_filename(m, at=None):
    """`{PAN}_{AY}_ITR1_{YYYYMMDDHHmmss}.json`"""
    pan = (m['personalInfo']['pan'] or 'UNKNOWNPAN').upper()
    if at:
        digits = ''.join(ch for ch in at if ch.isdigit())
        stamp = (digits + '0' * 14)[:14]
    else:
        stamp = compact_timestamp()
    return f"{pan}_{Constants['ay']}_ITR1_{stamp}.json"
