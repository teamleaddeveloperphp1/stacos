"""The computation engine.

Ported 1:1 from itr1-module/packages/core/src/engine/compute.ts.

ARCHITECTURE MANDATE 2: no magic numbers. Every rate, cap, threshold and date
comes from `itr1/data/ay2026-27/constants.json` via `CONSTANTS`.

ARCHITECTURE MANDATE 5: every derived value is computed here and nowhere else.

The model `m` is a plain nested Python dict (same shape as
`itr1.model_blank.blank_return_model()`), not a TS interface. `Computed` is
likewise represented as a plain nested Python dict with the same field
names/nesting as the TS `Computed` type, since `facts.py` and the serializer
read it the same way `facts.ts` does.

Every non-trivial figure carries a `Trace` (a `{"title": ..., "lines": [...]}`
dict) so "Show Computation" drawers can display the arithmetic line by line.
"""

import math

from itr1.engine.constants import CONSTANTS
from itr1.util.date import age_on, is_between_inclusive, months_or_part_from
from itr1.util.num import cap_at, n, pos, round_down_to_nearest, round_to_nearest, sum_by

Constants = CONSTANTS


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------


class TraceBuilder:
    def __init__(self, title):
        self.title = title
        self.lines = []

    def add(self, label, amount=None, detail=None):
        self.lines.append({'label': label, 'detail': detail, 'amount': amount})
        return self

    def result(self, label, amount, detail=None):
        self.lines.append({'label': label, 'detail': detail, 'amount': amount, 'result': True})
        return self

    def build(self):
        return {'title': self.title, 'lines': self.lines}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def compute(m):
    K = Constants
    regime = 'OLD' if m['filingStatus']['optOutOfNewRegime'] == 'Y' else 'NEW'
    emp_cat = m['personalInfo']['employerCategory']
    dob = m['personalInfo']['dob']

    is_senior_citizen_a13 = bool(dob) and dob <= K['seniorCitizen']['a13SeniorDOBOnOrBefore']
    is_senior_for_ttb = bool(dob) and dob <= K['seniorCitizen']['a13SeniorDOBOnOrBefore']
    age = age_on(dob, K['seniorCitizen']['ageReferenceDate']) if dob else None
    is_super_senior = age is not None and age >= K['seniorCitizen']['superSeniorMinAge']

    salary = compute_salary(m, regime)
    hra = compute_hra(m, regime)
    house_property = compute_house_property(m, regime)
    other_sources = compute_other_sources(m, regime)

    exempt_income_total = sum_by(m['income']['exemptIncome'], lambda r: r['amount'])
    agri_exempt_income = sum_by(
        [r for r in m['income']['exemptIncome'] if r.get('subCategory') == '10(1)' or r.get('category') == 'AGRI'],
        lambda r: r['amount'],
    )

    # A-218: LTCG 112A = (i - ii). A-217 caps it at 1,25,000 (validated, not clamped).
    ltcg_sale = n(m['income']['ltcg112A']['totalSaleConsideration'])
    ltcg_cost = n(m['income']['ltcg112A']['totalCostOfAcquisition'])
    ltcg112a = pos(ltcg_sale - ltcg_cost)

    # B4 — A-22 / A-174 / A-292
    gross_total_income = salary['incomeFromSalary'] + house_property['incomeForGti'] + other_sources['netIncomeOthSrc']
    gross_total_income_incl_ltcg = gross_total_income + ltcg112a

    deductions = compute_deductions(
        m,
        {
            'regime': regime,
            'empCat': emp_cat,
            'salary': salary,
            'otherSources': other_sources,
            'grossTotalIncome': gross_total_income,
            'grossTotalIncomeInclLtcg': gross_total_income_incl_ltcg,
            'ltcg112A': ltcg112a,
            'isSeniorCitizenA13': is_senior_citizen_a13,
            'isSeniorForTTB': is_senior_for_ttb,
            'age': age,
        },
    )
    total_deductions = deductions['total']

    # C2 — A-24: difference, or zero if negative; rounded to the nearest ₹10 (s.288A)
    total_income_unrounded = max(0, gross_total_income_incl_ltcg - total_deductions)
    total_income = round_to_nearest(total_income_unrounded, K['rounding']['totalIncomeNearest'])
    total_income_excl_ltcg = max(0, total_income - ltcg112a)

    tax = compute_tax(
        m,
        {
            'regime': regime,
            'totalIncome': total_income,
            'totalIncomeExclLtcg': total_income_excl_ltcg,
            'ltcg112A': ltcg112a,
            'age': age,
            'isSuperSenior': is_super_senior,
        },
    )

    taxes_paid = compute_taxes_paid(m)

    interest = compute_interest_and_fee(
        m,
        {
            'regime': regime,
            'tax': tax,
            'taxesPaid': taxes_paid,
            'totalIncome': total_income,
            'totalIncomeExclLtcg': total_income_excl_ltcg,
            'otherSources': other_sources,
        },
    )

    # D11 — A-27 / A-140
    total_tax_fee_and_interest = pos(
        round_to_nearest(tax['balanceTaxAfterRelief'] + interest['total'], K['rounding']['taxNearest'])
    )

    refund_raw = taxes_paid['total'] - total_tax_fee_and_interest
    refund_due = round_down_to_nearest(refund_raw, K['rounding']['refundNearest']) if refund_raw > 0 else 0
    balance_tax_payable = round_to_nearest(-refund_raw, K['rounding']['taxNearest']) if refund_raw < 0 else 0

    return {
        'constantsVersion': K['version'],
        'regime': regime,
        'employerCategory': emp_cat,
        'isSeniorCitizenA13': is_senior_citizen_a13,
        'isSeniorForTTB': is_senior_for_ttb,
        'isSuperSenior': is_super_senior,
        'age': age,
        'salary': salary,
        'hra': hra,
        'houseProperty': house_property,
        'otherSources': other_sources,
        'exemptIncomeTotal': exempt_income_total,
        'agriExemptIncome': agri_exempt_income,
        'ltcg112A': ltcg112a,
        'ltcg112ASubRows': {'sale': ltcg_sale, 'cost': ltcg_cost},
        'grossTotalIncome': gross_total_income,
        'grossTotalIncomeInclLtcg': gross_total_income_incl_ltcg,
        'deductions': deductions,
        'totalDeductions': total_deductions,
        'totalIncome': total_income,
        'totalIncomeUnrounded': total_income_unrounded,
        'totalIncomeExclLtcg': total_income_excl_ltcg,
        'tax': tax,
        'interest': interest,
        'totalTaxFeeAndInterest': total_tax_fee_and_interest,
        'taxesPaid': taxes_paid,
        'refundDue': refund_due,
        'balanceTaxPayable': balance_tax_payable,
        'refundBelowMinimumThreshold': refund_due > 0 and refund_due < K['rounding']['minimumRefundIssued'],
        'isBelatedOrLate': is_filed_after_due_date(m),
        'dueDate139_1': K['dueDates']['us139_1'],
        'filingDate': m['filingStatus']['filingDate'],
    }


def is_filed_after_due_date(m):
    K = Constants
    sec = m['filingStatus']['returnFileSec']
    # 139(4) belated and 139(5) revised are by definition after the due date;
    # otherwise compare the actual filing date.
    if sec in (12, 17, 20):
        return True
    filed = m['filingStatus']['filingDate']
    if not filed:
        return False
    return filed > K['dueDates']['us139_1']


# ---------------------------------------------------------------------------
# B1 — Salary
# ---------------------------------------------------------------------------


def compute_salary(m, regime):
    K = Constants
    inc = m['income']
    has_employers = len(inc['employers']) > 0

    salary17_1 = sum_by(inc['employers'], lambda e: e['salary17_1']) if has_employers else n(inc['salary17_1'])
    perquisites17_2 = (
        sum_by(inc['employers'], lambda e: e['perquisites17_2']) if has_employers else n(inc['perquisites17_2'])
    )
    profits_in_lieu17_3 = (
        sum_by(inc['employers'], lambda e: e['profitsInLieu17_3']) if has_employers else n(inc['profitsInLieu17_3'])
    )

    # A-59
    gross_salary = salary17_1 + perquisites17_2 + profits_in_lieu17_3
    # A-77
    total_exempt_allowances = sum_by(inc['exemptAllowances'], lambda r: r['amount'])
    # A-60
    net_salary = pos(gross_salary - total_exempt_allowances)

    # A-215 / A-112: capped at net salary (you cannot deduct more than you have)
    sd_cap = K['regimes'][regime]['standardDeduction16ia']
    standard_deduction16ia = min(sd_cap, net_salary)
    trace_standard_deduction = (
        TraceBuilder('Standard deduction u/s 16(ia)')
        .add(f"Statutory limit ({'new' if regime == 'NEW' else 'old'} regime)", sd_cap)
        .add('Net salary (B1iii)', net_salary)
        .result('Standard deduction allowed — lower of the two', standard_deduction16ia)
        .build()
    )

    # A-57 / A-58 / A-163
    ent_cfg = K['salary']['entertainmentAllowance16ii']
    ent_entered = n(inc['entertainmentAllowance16ii'])
    ent_eligible_employer = m['personalInfo']['employerCategory'] in ent_cfg['eligibleEmployerCategories']
    ent_trace = TraceBuilder('Entertainment allowance u/s 16(ii)')
    entertainment_allowance16ii = 0
    if regime == 'NEW':
        ent_trace.add('New regime — 16(ii) is not available (A-163)', 0)
    elif not ent_eligible_employer:
        ent_trace.add('Employer is not Central Government, State Government or PSU — not allowed (A-58)', 0)
    else:
        fifth = math.floor(ent_cfg['fractionOfSalary'] * salary17_1)
        ent_trace.add('Amount claimed', ent_entered).add('Statutory flat limit', ent_cfg['flatCap']).add(
            'One-fifth of salary u/s 17(1)', fifth
        )
        entertainment_allowance16ii = min(ent_entered, ent_cfg['flatCap'], fifth)
    ent_trace.result('Entertainment allowance allowed', entertainment_allowance16ii)

    # A-168
    professional_tax16iii = (
        0
        if regime == 'NEW'
        else min(n(inc['professionalTax16iii']), K['salary']['professionalTax16iii']['cap'])
    )

    # A-61
    deduction_us16 = min(
        standard_deduction16ia + entertainment_allowance16ii + professional_tax16iii,
        net_salary,
    )
    # A-62
    income_from_salary = pos(net_salary - deduction_us16)

    return {
        'salary17_1': salary17_1,
        'perquisites17_2': perquisites17_2,
        'profitsInLieu17_3': profits_in_lieu17_3,
        'grossSalary': gross_salary,
        'totalExemptAllowances': total_exempt_allowances,
        'netSalary': net_salary,
        'standardDeduction16ia': standard_deduction16ia,
        'entertainmentAllowance16ii': entertainment_allowance16ii,
        'professionalTax16iii': professional_tax16iii,
        'deductionUs16': deduction_us16,
        'incomeFromSalary': income_from_salary,
        'allowanceCeilings': allowance_ceilings(
            m,
            regime,
            {'salary17_1': salary17_1, 'grossSalary': gross_salary, 'perquisites17_2': perquisites17_2},
        ),
        'traceStandardDeduction': trace_standard_deduction,
        'traceEntertainment': ent_trace.build(),
    }


def allowance_ceilings(m, regime, base):
    """The per-section ceiling for every exempt allowance. Returned as data so the
    UI can show live "limit / remaining" helper text and so the rule registry can
    cite one figure rather than re-deriving it."""
    K = Constants
    caps = K['salary']['exemptAllowanceCaps']
    emp_cat = m['personalInfo']['employerCategory']
    tds192 = sum_by(m['taxPaid']['tds1'], lambda r: r['totalTaxDeducted'])

    gratuity_cap = (
        caps['gratuity10_10']['cap25L']  # A-267
        if emp_cat in caps['gratuity10_10']['cap25LCategories']
        else caps['gratuity10_10']['cap20L']  # A-67
    )

    out = {
        '10(5)': 0 if regime == 'NEW' else base['salary17_1'],  # A-64 / A-149 / A-164
        '10(6)': base['grossSalary'],  # A-65
        '10(7)': base['grossSalary'],  # A-66
        '10(10)': gratuity_cap,
        '10(10A)': base['salary17_1'],  # A-68
        '10(10AA)': base['salary17_1'],  # A-69 (A-142 adds a ₹25L block for non-govt)
        '10(10B)(i)': caps['comp10_10B_i']['cap'],  # A-70
        '10(10B)(ii)': caps['comp10_10B_ii']['cap'],  # A-188
        '10(10C)': caps['vrs10_10C']['cap'],  # A-71
        '10(10CC)': min(base['perquisites17_2'], tds192),  # A-73 / A-177
        '10(13A)': (
            0  # A-165 / A-149
            if regime == 'NEW'
            else min(
                base['salary17_1'],  # A-74
                math.floor(caps['hra10_13A']['fractionOfSalary17_1'] * base['salary17_1']),  # A-176
            )
        ),
        '10(14)(i)': 0 if regime == 'NEW' else base['salary17_1'],  # A-75 / A-166
        '10(14)(ii)': 0 if regime == 'NEW' else base['salary17_1'],  # A-76 / A-167
        # A-150 blocks the 115BAC-specific sub-clauses under the old regime;
        # A-148 caps the handicapped transport allowance under the new regime.
        '10(14)(i)(115BAC)': 0 if regime == 'OLD' else None,
        '10(14)(ii)(115BAC)': (
            0 if regime == 'OLD' else caps['allw10_14_ii']['handicappedTransportNewRegimeCap']
        ),
        '10(17)': 0 if regime == 'NEW' else None,  # A-37 / A-161
        # A-270 / A-301 — judge's exempt income
        'EIC': (
            0
            if regime == 'NEW'
            else (None if emp_cat in K['salary']['judgeExemptIncomeAllowedCategories'] else 0)
        ),
    }
    return out


# ---------------------------------------------------------------------------
# Schedule 10(13A) — HRA least-of
# ---------------------------------------------------------------------------


def compute_hra(m, regime):
    K = Constants['hra10_13A']
    h = m['income']['hra10_13A']
    salary_plus_da = n(h['basicSalary']) + n(h['dearnessAllowance'])
    actual_hra_received = n(h['actualHraReceived'])

    # A-261
    rent_paid_less_10_percent_of_salary = pos(
        n(h['actualRentPaid']) - math.floor(K['rentLessPercentOfSalary'] * salary_plus_da)
    )
    # A-262
    is_metro = h['placeOfWork'] == K['placeOfWorkEnum']['metro']
    fraction = K['metroFraction'] if is_metro else K['nonMetroFraction']
    salary40_or_50_percent = math.floor(fraction * salary_plus_da)

    # A-263 — least of the three
    eligible_exemption = (
        0
        if regime == 'NEW'
        else min(actual_hra_received, rent_paid_less_10_percent_of_salary, salary40_or_50_percent)
    )

    trace = (
        TraceBuilder('HRA exemption u/s 10(13A) — least of the following')
        .add('A. Actual HRA received', actual_hra_received)
        .add(
            'B. Actual rent paid less 10% of (basic + DA)',
            rent_paid_less_10_percent_of_salary,
            f"Rent {n(h['actualRentPaid'])} − 10% of {salary_plus_da}",
        )
        .add(
            f"C. {'50%' if is_metro else '40%'} of (basic + DA)",
            salary40_or_50_percent,
            'Metro city' if is_metro else 'Non-metro city',
        )
    )
    if regime == 'NEW':
        trace.add('New regime — 10(13A) is not available (A-165)', 0)
    trace.result('Eligible exemption u/s 10(13A)', eligible_exemption)

    return {
        'actualHraReceived': actual_hra_received,
        'rentPaidLess10PercentOfSalary': rent_paid_less_10_percent_of_salary,
        'salary40Or50Percent': salary40_or_50_percent,
        'eligibleExemption': eligible_exemption,
        # A-266
        'basicPlusDaPlusHra': n(h['basicSalary']) + n(h['dearnessAllowance']) + actual_hra_received,
        'trace': trace.build(),
    }


# ---------------------------------------------------------------------------
# B2 — House property
# ---------------------------------------------------------------------------


def compute_house_property(m, regime):
    K = Constants['houseProperty']
    props = [compute_property(p, regime) for p in m['income']['properties']]
    head_income = sum(p['incomeOfHP'] for p in props)

    income_for_gti = head_income
    loss_set_off_restricted = False
    trace = TraceBuilder('Income from house property')
    for p in props:
        trace.add(f"Property {p['id'][:8]} — income/(loss)", p['incomeOfHP'])
    if head_income < 0:
        if regime == 'NEW':
            # A-160: under the new regime the loss is not set off against other heads.
            income_for_gti = 0
            loss_set_off_restricted = True
            trace.add('New regime — house property loss is not set off (A-160)', 0)
        elif head_income < -K['maxSetOffLossAgainstOtherHeads']:
            income_for_gti = -K['maxSetOffLossAgainstOtherHeads']
            loss_set_off_restricted = True
            trace.add(
                f"Loss set off against other heads is capped at ₹{K['maxSetOffLossAgainstOtherHeads']}",
                income_for_gti,
            )
    trace.result('Amount taken into Gross Total Income', income_for_gti)

    return {
        'properties': props,
        'headIncome': head_income,
        'incomeForGti': income_for_gti,
        'lossSetOffRestricted': loss_set_off_restricted,
        'trace': trace.build(),
    }


def compute_property(p, regime):
    K = Constants['houseProperty']
    is_self_occupied = p['propertyType'] == 'S'

    gross_rent = 0 if is_self_occupied else n(p['grossRent'])
    rent_not_realized = 0 if is_self_occupied else n(p['rentNotRealized'])
    # A-49: local taxes are not allowed for a self-occupied property.
    local_taxes = 0 if is_self_occupied else n(p['localTaxes'])

    # 1d — A-298
    total_unrealized_and_tax = rent_not_realized + local_taxes
    # 1e — A-46
    balance_annual_value = pos(gross_rent - total_unrealized_and_tax)

    share_percent = n(p['assesseeSharePercent']) if p['coOwned'] == 'YES' else 100
    # 1f — A-296
    annual_value_of_share = round(balance_annual_value * share_percent / 100)
    # 1g — A-43
    thirty_percent = round(K['standardDeductionRate'] * annual_value_of_share)

    interest_entered = n(p['interestOnBorrowedCapital'])
    interest_cap = None
    if is_self_occupied:
        # A-48 (old) / A-162, A-253 (new)
        interest_cap = K['selfOccupiedInterestCapOld'] if regime == 'OLD' else K['selfOccupiedInterestCapNew']
    # A-297: a zero share means no interest can be claimed.
    if p['coOwned'] == 'YES' and share_percent == 0:
        interest_cap = 0
    interest_allowed = cap_at(interest_entered, interest_cap)

    # 1i — A-299
    total_deduct = thirty_percent + interest_allowed
    arrears = n(p['arrearsUnrealisedRentReceived'])
    # 1k — A-47
    income_of_hp = annual_value_of_share - total_deduct + arrears

    return {
        'id': p['id'],
        'grossRent': gross_rent,
        'rentNotRealized': rent_not_realized,
        'localTaxes': local_taxes,
        'totalUnrealizedAndTax': total_unrealized_and_tax,
        'balanceAnnualValue': balance_annual_value,
        'annualValueOfShare': annual_value_of_share,
        'thirtyPercent': thirty_percent,
        'interestAllowed': interest_allowed,
        'interestEntered': interest_entered,
        'interestCap': interest_cap,
        'totalDeduct': total_deduct,
        'arrears': arrears,
        'incomeOfHP': income_of_hp,
        # A-246
        'schedule24BTotal': sum_by(p['schedule24B'], lambda r: r['interestPaid']),
        # A-295 / A-333
        'coOwnersShareTotal': sum_by(p['coOwners'], lambda c: c['sharePercent']),
    }


# ---------------------------------------------------------------------------
# B3 — Other sources
# ---------------------------------------------------------------------------


def compute_other_sources(m, regime):
    K = Constants['otherSources']['deduction57iia'][regime]
    rows = [{'id': r['id'], 'nature': r['nature'], 'amount': n(r['amount'])} for r in m['income']['otherSources']]

    def by_nature(nature):
        return sum_by([r for r in rows if r['nature'] == nature], lambda r: r['amount'])

    # A-52
    gross_total = sum(r['amount'] for r in rows)
    savings_interest = by_nature('SAV')
    deposit_interest = by_nature('IFD')
    family_pension = by_nature('FAP')
    dividend_total = by_nature('DIV')

    # A-145
    dividend_quarterly = {q['key']: 0 for q in Constants['quarterlyBreakup']}
    for r in m['income']['otherSources']:
        if r['nature'] != 'DIV' or not r.get('dividendQuarterly'):
            continue
        for q in Constants['quarterlyBreakup']:
            dividend_quarterly[q['key']] += n(r['dividendQuarterly'].get(q['key']))

    interest_income_total = savings_interest + deposit_interest + by_nature('TAX')

    # A-53 / A-54 (old) / A-214 (new)
    one_third = math.floor(K['fractionOfFamilyPension'] * family_pension)
    deduction57iia_cap = min(one_third, K['cap']) if family_pension > 0 else 0
    deduction57iia = deduction57iia_cap

    net_income_oth_src = pos(gross_total - deduction57iia)

    trace = (
        TraceBuilder('Income from other sources')
        .add('Sum of individual rows (A-52)', gross_total)
        .add('Family pension included above', family_pension)
        .add(f"Deduction u/s 57(iia) — lower of one-third ({one_third}) or ₹{K['cap']}", deduction57iia)
        .result("Income chargeable under 'Other Sources'", net_income_oth_src)
        .build()
    )

    return {
        'rows': rows,
        'grossTotal': gross_total,
        'savingsInterest': savings_interest,
        'depositInterest': deposit_interest,
        'familyPension': family_pension,
        'dividendTotal': dividend_total,
        'dividendQuarterly': dividend_quarterly,
        'interestIncomeTotal': interest_income_total,
        'deduction57iia': deduction57iia,
        'deduction57iiaCap': deduction57iia_cap,
        'netIncomeOthSrc': net_income_oth_src,
        'trace': trace,
    }


# ---------------------------------------------------------------------------
# Chapter VI-A
# ---------------------------------------------------------------------------


def compute_deductions(m, ctx):
    K = Constants['chapterVIA']
    d = m['deductions']
    is_new = ctx['regime'] == 'NEW'
    by_section = {}
    traces = {}

    def put(section, entered, eligible, cap, cap_reason):
        cfg = K['sections'].get(section)
        available = (not is_new) or bool(cfg and cfg.get('newRegimeAllowed'))
        # A-146 and its companions: under the new regime every other section is 0.
        final_eligible = max(0, min(eligible, entered)) if available else 0
        by_section[section] = {
            'section': section,
            'entered': entered,
            'eligible': final_eligible,
            'cap': cap,
            'capReason': cap_reason if available else 'Not available under the new tax regime',
            'availableUnderRegime': available,
        }

    # --- Schedule totals used both for eligibility and for the A-24x rules ------
    schedule80c_total = sum_by(d['schedule80C'], lambda r: r['amount'])
    schedule80ccc_total = sum_by(d['pensionContribution80CCC'], lambda r: r['amount'])
    schedule80e_total = sum_by(d['schedule80E'], lambda r: r['interest'])
    schedule80ee_total = sum_by(d['schedule80EE'], lambda r: r['interest'])
    schedule80eea_total = sum_by(d['schedule80EEA'], lambda r: r['interest'])
    schedule80eeb_total = sum_by(d['schedule80EEB'], lambda r: r['interest'])

    # --- 80C / 80CCC / 80CCD(1): the ₹1,50,000 aggregate (A-1) -----------------
    agg_cap = K['aggregate80C_80CCC_80CCD1']
    e80c = min(n(d['s80C']), agg_cap)
    e80ccc = min(n(d['s80CCC']), max(0, agg_cap - e80c))

    # A-2 / A-3
    is_pensioner_or_na = ctx['empCat'] in K['s80CCD1']['pensionerOrNACategories']
    own80ccd1_cap = (
        math.floor(K['s80CCD1']['fractionOfGTIForPensioners'] * ctx['grossTotalIncome'])
        if is_pensioner_or_na
        else math.floor(K['s80CCD1']['fractionOfSalaryForOthers'] * ctx['salary']['salary17_1'])
    )
    e80ccd1 = min(n(d['s80CCD1']), own80ccd1_cap, max(0, agg_cap - e80c - e80ccc))

    put('80C', n(d['s80C']), e80c, agg_cap, f'Part of the ₹{agg_cap} aggregate u/s 80C + 80CCC + 80CCD(1)')
    put('80CCC', n(d['s80CCC']), e80ccc, agg_cap, f'Part of the ₹{agg_cap} aggregate')
    put(
        '80CCD1',
        n(d['s80CCD1']),
        e80ccd1,
        own80ccd1_cap,
        (
            f'20% of Gross Total Income (A-2) = ₹{own80ccd1_cap}'
            if is_pensioner_or_na
            else f'10% of salary u/s 17(1) (A-3) = ₹{own80ccd1_cap}'
        ),
    )
    traces['80C'] = (
        TraceBuilder('Deduction u/s 80C / 80CCC / 80CCD(1)')
        .add('Aggregate statutory limit (A-1)', agg_cap)
        .add('80C claimed', n(d['s80C']))
        .add('80C allowed', e80c)
        .add('80CCC claimed', n(d['s80CCC']))
        .add('80CCC allowed (balance of the aggregate)', e80ccc)
        .add('80CCD(1) claimed', n(d['s80CCD1']))
        .add(
            '80CCD(1) own limit — 20% of GTI' if is_pensioner_or_na else '80CCD(1) own limit — 10% of salary',
            own80ccd1_cap,
        )
        .result('80CCD(1) allowed', e80ccd1)
        .build()
    )

    # --- 80CCD(1B) — A-115 ----------------------------------------------------
    cap80ccd1b = K['sections']['80CCD1B']['cap']
    put('80CCD1B', n(d['s80CCD1B']), min(n(d['s80CCD1B']), cap80ccd1b), cap80ccd1b, f'₹{cap80ccd1b} limit')

    # --- 80CCD(2) — A-4 / A-116 / A-120 / A-216 -------------------------------
    c2 = K['s80CCD2']
    blocked80ccd2 = ctx['empCat'] in c2['blockedCategories']
    cap80ccd2 = 0
    reason80ccd2 = ''
    if blocked80ccd2:
        reason80ccd2 = 'Not available for pensioner categories or "Not Applicable" (A-116)'
    elif is_new:
        allowed = ctx['empCat'] in c2['newRegime']['allowedCategories']
        cap80ccd2 = math.floor(c2['newRegime']['fraction'] * ctx['salary']['salary17_1']) if allowed else 0
        reason80ccd2 = (
            f"14% of salary u/s 17(1) (A-216) = ₹{cap80ccd2}"
            if allowed
            else 'Employer category not eligible under the new regime (A-216)'
        )
    else:
        is_govt = ctx['empCat'] in c2['oldRegime']['govtCategories']
        fr = c2['oldRegime']['govtFraction'] if is_govt else c2['oldRegime']['otherFraction']
        cap80ccd2 = math.floor(fr * ctx['salary']['salary17_1'])
        reason80ccd2 = f"{fr * 100:.0f}% of salary u/s 17(1) ({'A-120' if is_govt else 'A-4'}) = ₹{cap80ccd2}"
    put('80CCD2', n(d['s80CCD2']), min(n(d['s80CCD2']), cap80ccd2), cap80ccd2, reason80ccd2)
    traces['80CCD2'] = (
        TraceBuilder('Deduction u/s 80CCD(2)')
        .add('Salary u/s 17(1)', ctx['salary']['salary17_1'])
        .add('Amount claimed', n(d['s80CCD2']))
        .add(reason80ccd2, cap80ccd2)
        .result('Allowed', by_section['80CCD2']['eligible'])
        .build()
    )

    # --- 80CCH — A-186 / A-187 / A-291 ---------------------------------------
    cch = K['s80CCH']
    cch_employer_ok = ctx['empCat'] in cch['allowedEmployerCategories']
    join_age = (
        age_on(m['personalInfo']['dob'], m['personalInfo']['armedForcesJoiningDate'])
        if m['personalInfo']['armedForcesJoiningDate']
        else None
    )
    cch_age_ok = join_age is not None and cch['minAgeAtJoining'] <= join_age <= cch['maxAgeAtJoining']
    cch_cap = math.floor(cch['fractionOfSalary17_1'] * ctx['salary']['salary17_1'])
    cch_eligible = min(n(d['s80CCH']), cch_cap) if (cch_employer_ok and cch_age_ok) else 0
    put(
        '80CCH',
        n(d['s80CCH']),
        cch_eligible,
        cch_cap,
        (
            "80CCH is not allowed for employment category other than 'Central Government' (A-187)"
            if not cch_employer_ok
            else (
                f"Age at the date of joining the armed forces must be between {cch['minAgeAtJoining']} and {cch['maxAgeAtJoining']} (A-187)"
                if not cch_age_ok
                else f"46.2% of salary u/s 17(1) (A-186) = ₹{cch_cap}"
            )
        ),
    )

    # --- 80D — A-127 to A-138 -------------------------------------------------
    schedule80d = compute_80d(m, ctx)
    put(
        '80D',
        n(d['s80D']),
        min(n(d['s80D']), schedule80d['eligibleAmountOfDeduction']),
        K['s80D']['totalCap'],
        f"Eligible amount per Schedule 80D = ₹{schedule80d['eligibleAmountOfDeduction']}",
    )
    traces['80D'] = schedule80d['trace']

    # --- 80DD / 80U — exact statutory amounts (A-200 to A-204) ---------------
    def fixed_disability(section, sched, entered):
        cfg = K['s80DD'] if section == '80DD' else K['s80U']
        statutory = (
            cfg['severeDisabilityAmount']
            if sched['natureOfDisability'] == '2'
            else cfg['disabilityAmount']
            if sched['natureOfDisability'] == '1'
            else 0
        )
        # "subject to GTI"
        allowed = min(statutory, max(0, ctx['grossTotalIncome']))
        put(
            section,
            entered,
            min(entered, allowed),
            allowed,
            (
                f"Statutory amount for {'severe disability' if sched['natureOfDisability'] == '2' else 'disability'} = ₹{statutory}, subject to Gross Total Income"
                if sched['natureOfDisability']
                else 'Nature of disability not selected'
            ),
        )

    fixed_disability('80DD', d['schedule80DD'], n(d['s80DD']))
    fixed_disability('80U', d['schedule80U'], n(d['s80U']))

    # --- 80DDB — A-5 / A-7 ---------------------------------------------------
    ddb_cap = K['s80DDB']['selfOrDependentCap'] if d['s80DDBUsrType'] == '1' else K['s80DDB']['cap']
    put(
        '80DDB',
        n(d['s80DDB']),
        min(n(d['s80DDB']), ddb_cap),
        ddb_cap,
        (
            f"₹{K['s80DDB']['selfOrDependentCap']} limit for the \"Self or Dependent\" category (A-7)"
            if d['s80DDBUsrType'] == '1'
            else f"₹{K['s80DDB']['cap']} limit (A-5)"
        ),
    )

    # --- 80E / 80EE / 80EEA / 80EEB -----------------------------------------
    put('80E', n(d['s80E']), n(d['s80E']), None, 'No monetary limit; must equal the Schedule 80E total (A-242)')
    put(
        '80EE',
        n(d['s80EE']),
        min(n(d['s80EE']), K['s80EE']['cap']),
        K['s80EE']['cap'],
        f"₹{K['s80EE']['cap']} limit (A-121)",
    )
    # A-123: 80EE and 80EEA are mutually exclusive; 80EEA takes precedence when both are claimed.
    e80eea = min(n(d['s80EEA']), K['s80EEA']['cap'])
    put('80EEA', n(d['s80EEA']), e80eea, K['s80EEA']['cap'], f"₹{K['s80EEA']['cap']} limit (A-122)")
    put(
        '80EEB',
        n(d['s80EEB']),
        min(n(d['s80EEB']), K['s80EEB']['cap']),
        K['s80EEB']['cap'],
        f"₹{K['s80EEB']['cap']} limit (A-124)",
    )

    # --- 80TTA — A-11 / A-12 / A-13 -----------------------------------------
    tta_cap = 0 if ctx['isSeniorCitizenA13'] else min(K['s80TTA']['cap'], ctx['otherSources']['savingsInterest'])
    put(
        '80TTA',
        n(d['s80TTA']),
        min(n(d['s80TTA']), tta_cap),
        tta_cap,
        (
            'Not available to a senior citizen (A-13)'
            if ctx['isSeniorCitizenA13']
            else f"Lower of ₹{K['s80TTA']['cap']} and savings-account interest of ₹{ctx['otherSources']['savingsInterest']} (A-11, A-12)"
        ),
    )

    # --- 80TTB — A-14 / A-15 / A-16 -----------------------------------------
    ttb_cap = (
        0
        if not ctx['isSeniorForTTB']
        else min(K['s80TTB']['cap'], ctx['otherSources']['interestIncomeTotal'])
    )
    put(
        '80TTB',
        n(d['s80TTB']),
        min(n(d['s80TTB']), ttb_cap),
        ttb_cap,
        (
            'Available only to an assessee aged 60 or more (A-15)'
            if not ctx['isSeniorForTTB']
            else f"Lower of ₹{K['s80TTB']['cap']} and interest income of ₹{ctx['otherSources']['interestIncomeTotal']} (A-14, A-16)"
        ),
    )

    # --- 80GGA — A-89 to A-94, A-118, A-143 ---------------------------------
    s80gga = compute_80gga(m)
    put(
        '80GGA',
        n(d['s80GGA']),
        min(n(d['s80GGA']), s80gga['eligible']),
        s80gga['eligible'],
        f"Eligible amount per Schedule 80GGA = ₹{s80gga['eligible']} (A-93)",
    )

    # --- 80GGC — A-193 to A-199, A-211 --------------------------------------
    s80ggc = compute_80ggc(m, ctx['grossTotalIncome'])
    put(
        '80GGC',
        n(d['s80GGC']),
        min(n(d['s80GGC']), s80ggc['eligible']),
        s80ggc['eligible'],
        f"Eligible amount per Schedule 80GGC = ₹{s80ggc['eligible']} (A-196)",
    )

    # --- 80G — needs the adjusted GTI, so it comes after the others ----------
    other_deductions_so_far = sum(x['eligible'] for x in by_section.values())
    schedule80g = compute_80g(
        m,
        {
            'grossTotalIncome': ctx['grossTotalIncome'],
            'ltcg112A': ctx['ltcg112A'],
            'otherDeductions': other_deductions_so_far,
        },
    )
    put(
        '80G',
        n(d['s80G']),
        min(n(d['s80G']), schedule80g['totalEligible']),
        schedule80g['totalEligible'],
        f"Eligible amount per Schedule 80G = ₹{schedule80g['totalEligible']} (A-10)",
    )
    traces['80G'] = schedule80g['trace']

    # --- 80GG — A-114 / A-119 ----------------------------------------------
    gg = K['s80GG']
    total_income_excl_ltcg_before_80gg = max(
        0,
        ctx['grossTotalIncome'] - (other_deductions_so_far + by_section['80G']['eligible']),
    )
    hra_claimed = sum_by(
        [r for r in m['income']['exemptAllowances'] if r['nature'] == '10(13A)'],
        lambda r: r['amount'],
    )
    gg_cap = (
        0
        if hra_claimed > 0
        else min(gg['flatCap'], math.floor(gg['fractionOfTotalIncomeExclLTCG'] * total_income_excl_ltcg_before_80gg))
    )
    put(
        '80GG',
        n(d['s80GG']),
        min(n(d['s80GG']), gg_cap),
        gg_cap,
        (
            'HRA u/s 10(13A) has been claimed, so 80GG is not allowed for the corresponding period (A-119)'
            if hra_claimed > 0
            else f"Lower of ₹{gg['flatCap']} and 25% of total income excluding LTCG before this deduction (₹{total_income_excl_ltcg_before_80gg}) (A-114)"
        ),
    )
    traces['80GG'] = (
        TraceBuilder('Deduction u/s 80GG')
        .add('Total income excluding LTCG, before this deduction', total_income_excl_ltcg_before_80gg)
        .add(
            '25% thereof',
            math.floor(gg['fractionOfTotalIncomeExclLTCG'] * total_income_excl_ltcg_before_80gg),
        )
        .add('Statutory flat limit', gg['flatCap'])
        .add('Amount claimed', n(d['s80GG']))
        .result('Allowed', by_section['80GG']['eligible'])
        .build()
    )

    # --- Totals — A-17 / A-18 ----------------------------------------------
    total_before_gti_restriction = sum(x['eligible'] for x in by_section.values())
    total = min(total_before_gti_restriction, max(0, ctx['grossTotalIncome']))

    return {
        'bySection': by_section,
        'total': total,
        'totalBeforeGtiRestriction': total_before_gti_restriction,
        'aggregate80CGroup': e80c + e80ccc + e80ccd1,
        'schedule80D': schedule80d,
        'schedule80G': schedule80g,
        'schedule80GGA': s80gga,
        'schedule80GGC': s80ggc,
        'schedule80CTotal': schedule80c_total,
        'schedule80CCCTotal': schedule80ccc_total,
        'schedule80ETotal': schedule80e_total,
        'schedule80EETotal': schedule80ee_total,
        'schedule80EEATotal': schedule80eea_total,
        'schedule80EEBTotal': schedule80eeb_total,
        'traces': traces,
    }


def compute_80d(m, ctx):
    K = Constants['chapterVIA']['s80D']
    s = m['deductions']['schedule80D']

    def block(b, cap, include_medical, claimable):
        health_insurance = n(b['healthInsurancePremium']) if claimable else 0
        preventive = min(n(b['preventiveHealthCheckup']), K['preventiveHealthCheckupCap']) if claimable else 0
        medical = n(b['medicalExpenditure']) if (claimable and include_medical) else 0
        raw_total = health_insurance + preventive + medical
        return {
            'healthInsurance': health_insurance,
            'insurersTotal': sum_by(b['insurers'], lambda i: i['amount']),
            'preventiveHealthCheckup': preventive,
            'medicalExpenditure': medical,
            'rawTotal': raw_total,
            'cap': cap,
            'deduction': min(raw_total, cap),
        }

    # A-178 to A-183: 1a is claimable only when the flag is "N", 1b only when "Y",
    # and neither when the flag is "S" (Not claiming for Self/Family). Same for 2a/2b.
    self_family = block(s['selfFamily'], K['selfFamilyCap'], False, s['selfFamilySeniorFlag'] == 'N')
    self_family_senior = block(
        s['selfFamilySenior'], K['selfFamilySeniorCap'], True, s['selfFamilySeniorFlag'] == 'Y'
    )
    parents = block(s['parents'], K['parentsCap'], False, s['parentsSeniorFlag'] == 'N')
    parents_senior = block(s['parentsSenior'], K['parentsSeniorCap'], True, s['parentsSeniorFlag'] == 'Y')

    preventive_total_across_blocks = (
        self_family['preventiveHealthCheckup']
        + self_family_senior['preventiveHealthCheckup']
        + parents['preventiveHealthCheckup']
        + parents_senior['preventiveHealthCheckup']
    )

    # A-137: 1a + 1b + 2a + 2b, subject to GTI and the ₹1,00,000 overall cap (A-136)
    raw = self_family['deduction'] + self_family_senior['deduction'] + parents['deduction'] + parents_senior['deduction']
    eligible_amount_of_deduction = min(raw, K['totalCap'], max(0, ctx['grossTotalIncome']))

    trace = (
        TraceBuilder('Deduction u/s 80D — Schedule 80D')
        .add(f"1a Self / Family (limit ₹{K['selfFamilyCap']})", self_family['deduction'])
        .add(f"1b Self / Family including senior citizen (limit ₹{K['selfFamilySeniorCap']})", self_family_senior['deduction'])
        .add(f"2a Parents (limit ₹{K['parentsCap']})", parents['deduction'])
        .add(f"2b Parents including senior citizen (limit ₹{K['parentsSeniorCap']})", parents_senior['deduction'])
        .add(
            'Preventive health check-up across all rows',
            preventive_total_across_blocks,
            f"Capped at ₹{K['preventiveHealthCheckupCap']}",
        )
        .add('Overall limit', K['totalCap'])
        .result('3. Eligible amount of deduction', eligible_amount_of_deduction)
        .build()
    )

    return {
        'selfFamily': self_family,
        'selfFamilySenior': self_family_senior,
        'parents': parents,
        'parentsSenior': parents_senior,
        'preventiveTotalAcrossBlocks': preventive_total_across_blocks,
        'eligibleAmountOfDeduction': eligible_amount_of_deduction,
        'trace': trace,
    }


def compute_80g(m, ctx):
    K = Constants['chapterVIA']['s80G']
    sch = m['deductions']['schedule80G']

    # Adjusted gross total income for the s.80G qualifying limit: gross total
    # income reduced by long-term capital gains and by every other Chapter VI-A
    # deduction. 10% of that figure caps tables (C) and (D).
    adjusted_gross_total_income = max(0, ctx['grossTotalIncome'] - ctx['ltcg112A'] - ctx['otherDeductions'])
    qualifying_limit = math.floor(0.1 * adjusted_gross_total_income)

    # A-88 / A-327, implemented literally as written: aggregate cash per donee
    # PAN across the whole schedule; if the aggregate exceeds ₹2,000 the cash
    # component is disallowed entirely, otherwise it is allowed up to ₹2,000.
    cash_by_pan = {}
    all_blocks = [
        ('Don100Percent', sch['don100Percent']),
        ('Don50PercentNoApprReqd', sch['don50PercentNoApprReqd']),
        ('Don100PercentApprReqd', sch['don100PercentApprReqd']),
        ('Don50PercentApprReqd', sch['don50PercentApprReqd']),
    ]
    for _, rows in all_blocks:
        for r in rows:
            pan = (r['pan'] or '').upper()
            cash_by_pan[pan] = cash_by_pan.get(pan, 0) + n(r['donationCash'])

    rate = {
        'Don100Percent': 1,
        'Don50PercentNoApprReqd': 0.5,
        'Don100PercentApprReqd': 1,
        'Don50PercentApprReqd': 0.5,
    }
    subject_to_qualifying_limit = {
        'Don100Percent': False,
        'Don50PercentNoApprReqd': False,
        'Don100PercentApprReqd': True,
        'Don50PercentApprReqd': True,
    }

    blocks = {}
    # Tables (C) and (D) share the single 10% ceiling; apply it in table order.
    qualifying_limit_remaining = qualifying_limit

    for key, rows in all_blocks:
        computed_rows = []
        for r in rows:
            cash = n(r['donationCash'])
            other = n(r['donationOtherMode'])
            pan_cash = cash_by_pan.get((r['pan'] or '').upper(), 0)
            cash_disallowed = pan_cash > K['cashDonationCap']
            allowed_cash = 0 if cash_disallowed else min(cash, K['cashDonationCap'])
            qualifying_donation = allowed_cash + other
            eligible_donation = math.floor(rate[key] * qualifying_donation)
            if subject_to_qualifying_limit[key]:
                capped = min(qualifying_donation, qualifying_limit_remaining)
                qualifying_limit_remaining = max(0, qualifying_limit_remaining - capped)
                eligible_donation = math.floor(rate[key] * capped)
            computed_rows.append(
                {
                    'id': r['id'],
                    'pan': r['pan'],
                    'donationCash': cash,
                    'donationOtherMode': other,
                    'donationTotal': cash + other,  # A-84 to A-87
                    'qualifyingDonation': qualifying_donation,
                    'eligibleDonation': eligible_donation,
                    'cashDisallowed': cash_disallowed,
                }
            )
        blocks[key] = {
            'key': key,
            'rows': computed_rows,
            'totalCash': sum(r['donationCash'] for r in computed_rows),
            'totalOtherMode': sum(r['donationOtherMode'] for r in computed_rows),
            'total': sum(r['donationTotal'] for r in computed_rows),
            'totalEligible': sum(r['eligibleDonation'] for r in computed_rows),
        }

    total_cash = sum(b['totalCash'] for b in blocks.values())
    total_other_mode = sum(b['totalOtherMode'] for b in blocks.values())
    total = sum(b['total'] for b in blocks.values())
    # A-139: eligible can never exceed total donations.
    total_eligible = min(sum(b['totalEligible'] for b in blocks.values()), total)

    trace = (
        TraceBuilder('Deduction u/s 80G — Schedule 80G')
        .add('Gross total income', ctx['grossTotalIncome'])
        .add('Less: LTCG u/s 112A', ctx['ltcg112A'])
        .add('Less: other Chapter VI-A deductions', ctx['otherDeductions'])
        .add('Adjusted gross total income', adjusted_gross_total_income)
        .add('Qualifying limit — 10% thereof', qualifying_limit)
        .add('(A) 100% without qualifying limit', blocks['Don100Percent']['totalEligible'])
        .add('(B) 50% without qualifying limit', blocks['Don50PercentNoApprReqd']['totalEligible'])
        .add('(C) 100% subject to qualifying limit', blocks['Don100PercentApprReqd']['totalEligible'])
        .add('(D) 50% subject to qualifying limit', blocks['Don50PercentApprReqd']['totalEligible'])
        .result('Total eligible donation', total_eligible)
        .build()
    )

    return {
        'blocks': blocks,
        'totalCash': total_cash,
        'totalOtherMode': total_other_mode,
        'total': total,
        'totalEligible': total_eligible,
        'qualifyingLimit': qualifying_limit,
        'adjustedGrossTotalIncome': adjusted_gross_total_income,
        'trace': trace,
    }


def compute_80gga(m):
    K = Constants['chapterVIA']['s80GGA']
    rows = m['deductions']['schedule80GGA']
    per_row = []
    for r in rows:
        cash = n(r['donationCash'])
        other = n(r['donationOtherMode'])
        # A-143: cash above ₹2,000 is not allowed.
        allowed_cash = 0 if cash > K['cashDonationCap'] else cash
        per_row.append({'id': r['id'], 'total': cash + other, 'eligible': allowed_cash + other})
    total_cash = sum_by(rows, lambda r: r['donationCash'])
    total_other_mode = sum_by(rows, lambda r: r['donationOtherMode'])
    total = total_cash + total_other_mode
    # A-92: eligible cannot exceed total.
    eligible = min(sum(r['eligible'] for r in per_row), total)
    return {'totalCash': total_cash, 'totalOtherMode': total_other_mode, 'total': total, 'eligible': eligible, 'perRow': per_row}


def compute_80ggc(m, gross_total_income):
    rows = m['deductions']['schedule80GGC']
    # A-194: eligible for each row = contribution in other mode, to the extent of GTI.
    # Cash contributions are not eligible at all.
    per_row = [
        {'id': r['id'], 'total': n(r['donationCash']) + n(r['donationOtherMode']), 'eligible': n(r['donationOtherMode'])}
        for r in rows
    ]
    total_cash = sum_by(rows, lambda r: r['donationCash'])
    total_other_mode = sum_by(rows, lambda r: r['donationOtherMode'])
    total = total_cash + total_other_mode
    # A-196: total eligible = sum of individual amounts, restricted to GTI.
    eligible = min(sum(r['eligible'] for r in per_row), max(0, gross_total_income))
    return {'totalCash': total_cash, 'totalOtherMode': total_other_mode, 'total': total, 'eligible': eligible, 'perRow': per_row}


# ---------------------------------------------------------------------------
# D1–D6 — Tax
# ---------------------------------------------------------------------------


def compute_tax(m, ctx):
    K = Constants
    cfg = K['regimes'][ctx['regime']]

    # Slab thresholds, with the old-regime senior/super-senior first-slab overrides.
    slabs = [dict(s) for s in cfg['slabs']]
    if ctx['regime'] == 'OLD':
        ov = K['regimes']['OLD']['seniorSlabOverrides']
        if ctx['isSuperSenior']:
            slabs = [s for s in slabs if s['upTo'] is None or s['upTo'] > ov['superSenior']['firstSlabUpTo']]
            slabs.insert(0, {'upTo': ov['superSenior']['firstSlabUpTo'], 'rate': 0})
        elif ctx['age'] is not None and ctx['age'] >= ov['senior']['minAge']:
            slabs = [s for s in slabs if s['upTo'] is None or s['upTo'] > ov['senior']['firstSlabUpTo']]
            slabs.insert(0, {'upTo': ov['senior']['firstSlabUpTo'], 'rate': 0})

    normal_rate_tax, slab_breakup = slab_tax(ctx['totalIncomeExclLtcg'], slabs)

    # LTCG u/s 112A at 12.5% on the excess over ₹1,25,000. Inside ITR-1 the LTCG
    # can never exceed ₹1,25,000 (A-217), so this is always nil — the portal shows
    # the note "The Total Income Field includes LTCG u/s 112A. However, no tax
    # would be payable on the said income."
    special_rate_tax = round(K['ltcg112A']['rate'] * max(0, ctx['ltcg112A'] - K['ltcg112A']['exemptThreshold']))

    tax_payable_on_total_income = round_to_nearest(normal_rate_tax + special_rate_tax, K['rounding']['taxNearest'])

    # D2 — rebate u/s 87A
    rb = cfg['rebate87A']
    rebate_base_income = ctx['totalIncomeExclLtcg'] if rb['excludeSpecialRateIncome'] else ctx['totalIncome']
    rebateable_tax = normal_rate_tax if rb['excludeSpecialRateIncome'] else normal_rate_tax + special_rate_tax

    trace_rebate = TraceBuilder('Rebate u/s 87A')
    rebate87a = 0
    rebate87a_marginal_relief = 0
    if rebate_base_income <= rb['incomeCeiling']:
        rebate87a = min(rebateable_tax, rb['maxRebate'])
        trace_rebate.add(
            'Total income excluding special-rate income' if rb['excludeSpecialRateIncome'] else 'Total income',
            rebate_base_income,
        ).add('Rebate threshold', rb['incomeCeiling']).add('Tax before rebate', rebateable_tax).add(
            'Maximum rebate', rb['maxRebate']
        ).result('Rebate allowed', rebate87a)
    elif rb['marginalRelief']:
        # Marginal relief: the tax payable cannot exceed the income in excess of the
        # threshold. This is what produces the ₹12,70,590 cut-off cited in A-191.
        excess = rebate_base_income - rb['incomeCeiling']
        rebate87a_marginal_relief = max(0, rebateable_tax - excess)
        rebate87a = min(rebate87a_marginal_relief, rb['maxRebate'])
        trace_rebate.add('Total income excluding special-rate income', rebate_base_income).add(
            'Rebate threshold', rb['incomeCeiling']
        ).add('Income in excess of the threshold', excess).add('Tax before rebate', rebateable_tax).add(
            'Marginal relief — tax less excess income', rebate87a_marginal_relief
        ).result('Rebate allowed', rebate87a)
    else:
        trace_rebate.add('Total income', rebate_base_income).add('Rebate threshold', rb['incomeCeiling']).result(
            'Rebate not available — income exceeds the threshold', 0
        )

    # A-25
    tax_payable_after_rebate = pos(tax_payable_on_total_income - rebate87a)
    education_cess = round(K['cessRate'] * tax_payable_after_rebate)
    # A-26
    total_tax_and_cess = tax_payable_after_rebate + education_cess
    relief89 = n(m['taxLiability']['relief89'])
    balance_tax_after_relief = pos(total_tax_and_cess - relief89)

    trace_tax = TraceBuilder('Tax payable on total income')
    for b in slab_breakup:
        if b['taxable'] <= 0:
            continue
        trace_tax.add(
            f"₹{b['from']:,} to {'above' if b['to'] is None else '₹' + format(b['to'], ',')} @ {b['rate'] * 100:.0f}%",
            b['tax'],
            f"on ₹{b['taxable']:,}",
        )
    if ctx['ltcg112A'] > 0:
        trace_tax.add(
            f"LTCG u/s 112A @ {K['ltcg112A']['rate'] * 100:.1f}% on the excess over ₹{K['ltcg112A']['exemptThreshold']:,}",
            special_rate_tax,
        )
    trace_tax.result('D1. Tax payable on total income', tax_payable_on_total_income)

    return {
        'taxPayableOnTotalIncome': tax_payable_on_total_income,
        'normalRateTax': normal_rate_tax,
        'specialRateTax': special_rate_tax,
        'slabBreakup': slab_breakup,
        'rebate87A': rebate87a,
        'rebate87AMarginalRelief': rebate87a_marginal_relief,
        'taxPayableAfterRebate': tax_payable_after_rebate,
        'educationCess': education_cess,
        'totalTaxAndCess': total_tax_and_cess,
        'relief89': relief89,
        'balanceTaxAfterRelief': balance_tax_after_relief,
        'traceTax': trace_tax.build(),
        'traceRebate': trace_rebate.build(),
    }


def slab_tax(income, slabs):
    lower = 0
    tax = 0
    breakup = []
    for s in slabs:
        upper = math.inf if s['upTo'] is None else s['upTo']
        taxable = max(0, min(income, upper) - lower)
        slice_ = round(s['rate'] * taxable)
        breakup.append({'from': lower, 'to': s['upTo'], 'rate': s['rate'], 'taxable': taxable, 'tax': slice_})
        tax += slice_
        lower = upper
        if income <= upper:
            break
    return tax, breakup


# ---------------------------------------------------------------------------
# Taxes paid
# ---------------------------------------------------------------------------


def compute_taxes_paid(m):
    K = Constants
    tp = m['taxPaid']

    # A-100 / A-101 / A-102 / A-97
    tds1 = sum_by(tp['tds1'], lambda r: r['totalTaxDeducted'])
    tds2 = sum_by(tp['tds2'], lambda r: r['tdsClaimedThisYear'])
    tds3 = sum_by(tp['tds3'], lambda r: r['tdsClaimedThisYear'])
    tcs = sum_by(tp['tcs'], lambda r: r['tcsClaimedThisYear'])

    # A-110 / A-111 — classified by the date of deposit, never by the user.
    cls = K['advanceTaxClassification']
    advance_tax = sum_by(
        [c for c in tp['challans'] if is_between_inclusive(c['dateOfDeposit'], cls['advanceTaxFrom'], cls['advanceTaxTo'])],
        lambda c: c['amount'],
    )
    self_assessment_tax = sum_by(
        [c for c in tp['challans'] if c['dateOfDeposit'] > cls['selfAssessmentAfter']],
        lambda c: c['amount'],
    )

    # Cumulative advance tax at each 234C installment date.
    advance_tax_cumulative = {}
    for inst in K['interestAndFee']['s234C']['installments']:
        advance_tax_cumulative[inst['label']] = sum_by(
            [c for c in tp['challans'] if is_between_inclusive(c['dateOfDeposit'], cls['advanceTaxFrom'], inst['dueDate'])],
            lambda c: c['amount'],
        )

    total_tds = tds1 + tds2 + tds3
    # A-103 / A-104
    total = total_tds + tcs + advance_tax + self_assessment_tax

    return {
        'tds1': tds1,
        'tds2': tds2,
        'tds3': tds3,
        'totalTds': total_tds,
        'tcs': tcs,
        'advanceTax': advance_tax,
        'selfAssessmentTax': self_assessment_tax,
        'total': total,
        'advanceTaxCumulative': advance_tax_cumulative,
        'tds192': tds1,
    }


# ---------------------------------------------------------------------------
# D7–D10a — Interest and fee
# ---------------------------------------------------------------------------


def compute_interest_and_fee(m, ctx):
    K = Constants['interestAndFee']
    due_date = Constants['dueDates']['us139_1']
    filing_date = m['filingStatus']['filingDate'] or due_date

    # "Assessed tax" for ss. 234A/234B/234C = tax on total income (including cess)
    # reduced by relief u/s 89, TDS, TCS. Advance tax is deducted separately where
    # the section requires it.
    tax_and_cess = ctx['tax']['totalTaxAndCess']
    assessed_tax = pos(tax_and_cess - ctx['tax']['relief89'] - ctx['taxesPaid']['totalTds'] - ctx['taxesPaid']['tcs'])

    # --- 234A ---------------------------------------------------------------
    t234a = TraceBuilder('Interest u/s 234A')
    interest234a_computed = 0
    if filing_date > due_date:
        months = months_or_part_from(due_date, filing_date)
        unpaid = pos(assessed_tax - ctx['taxesPaid']['advanceTax'] - ctx['taxesPaid']['selfAssessmentTax'])
        interest234a_computed = math.floor(K['s234A']['monthlyRate'] * months * unpaid)
        t234a.add('Tax and cess on total income', tax_and_cess).add(
            'Less: relief u/s 89, TDS, TCS, advance tax and self-assessment tax', -(tax_and_cess - unpaid)
        ).add('Tax remaining unpaid', unpaid).add(
            f'Months (or part) from {due_date} to {filing_date}', months
        ).result(f"Interest @ {K['s234A']['monthlyRate'] * 100:.0f}% per month", interest234a_computed)
    else:
        t234a.result('Return filed on or before the due date — no interest u/s 234A', 0)

    # --- 234B ---------------------------------------------------------------
    t234b = TraceBuilder('Interest u/s 234B')
    interest234b_computed = 0
    ninety_percent = math.floor(K['s234B']['advanceTaxThresholdFraction'] * assessed_tax)
    if assessed_tax > 0 and ctx['taxesPaid']['advanceTax'] < ninety_percent:
        months = months_or_part_from(K['s234B']['startDate'], filing_date)
        shortfall = pos(assessed_tax - ctx['taxesPaid']['advanceTax'])
        interest234b_computed = math.floor(K['s234B']['monthlyRate'] * months * shortfall)
        t234b.add('Assessed tax', assessed_tax).add('90% of assessed tax', ninety_percent).add(
            'Advance tax paid', ctx['taxesPaid']['advanceTax']
        ).add('Shortfall', shortfall).add(
            f"Months (or part) from {K['s234B']['startDate']} to {filing_date}", months
        ).result(f"Interest @ {K['s234B']['monthlyRate'] * 100:.0f}% per month", interest234b_computed)
    else:
        t234b.result(
            'No assessed tax outstanding — no interest u/s 234B'
            if assessed_tax <= 0
            else 'Advance tax paid is at least 90% of assessed tax — no interest u/s 234B',
            0,
        )

    # --- 234C ---------------------------------------------------------------
    t234c = TraceBuilder('Interest u/s 234C')
    interest234c = 0
    if assessed_tax >= K['s234C']['minimumAssessedTax']:
        # The first proviso to s.234C(1) excludes shortfall attributable to dividend
        # income that arose after the installment due date, provided the tax is paid
        # in the remaining installments. Approximate the tax on that dividend income
        # at the average rate of tax on total income.
        avg_rate = tax_and_cess / ctx['totalIncome'] if ctx['totalIncome'] > 0 else 0
        quarters = Constants['quarterlyBreakup']

        for inst in K['s234C']['installments']:
            paid = ctx['taxesPaid']['advanceTaxCumulative'].get(inst['label'], 0)
            base = assessed_tax
            if K['s234C']['dividendProvisoApplies']:
                dividend_after = sum(
                    n(ctx['otherSources']['dividendQuarterly'].get(q['key']))
                    for q in quarters
                    if q['from'] > inst['dueDate']
                )
                base = pos(assessed_tax - round(avg_rate * dividend_after))
            safe_harbour = math.floor(inst['safeHarbourFraction'] * base)
            if paid >= safe_harbour:
                t234c.add(f"{inst['label']} — paid ₹{paid} against the safe harbour of ₹{safe_harbour}", 0)
                continue
            required = math.floor(inst['requiredFraction'] * base)
            shortfall = pos(required - paid)
            amount = math.floor(K['s234C']['monthlyRate'] * inst['months'] * shortfall)
            interest234c += amount
            t234c.add(
                f"{inst['label']} — shortfall ₹{shortfall} x {K['s234C']['monthlyRate'] * 100:.0f}% x {inst['months']} month(s)",
                amount,
                f'required ₹{required}, paid ₹{paid}',
            )
        t234c.result('Total interest u/s 234C', interest234c)
    else:
        t234c.result(f"Assessed tax is below ₹{K['s234C']['minimumAssessedTax']} — no interest u/s 234C", 0)

    # --- 234F ---------------------------------------------------------------
    t234f = TraceBuilder('Fee u/s 234F')
    fee234f_computed = 0
    basic_exemption = (
        Constants['regimes']['NEW']['basicExemptionLimit']
        if ctx['regime'] == 'NEW'
        else (old_regime_basic_exemption(m) if ctx['totalIncome'] > 0 else 0)
    )
    if filing_date <= due_date:
        t234f.result('Return filed on or before the due date — no fee u/s 234F', 0)
    elif ctx['totalIncome'] < basic_exemption:
        t234f.add('Total income', ctx['totalIncome']).add('Basic exemption limit', basic_exemption).result(
            'Total income is below the basic exemption limit — no fee u/s 234F', 0
        )
    else:
        fee234f_computed = (
            K['s234F']['reducedFee'] if ctx['totalIncome'] <= K['s234F']['reducedFeeIncomeCeiling'] else K['s234F']['standardFee']
        )
        t234f.add('Total income', ctx['totalIncome']).add(
            'Threshold for the reduced fee', K['s234F']['reducedFeeIncomeCeiling']
        ).result('Fee u/s 234F', fee234f_computed)

    # --- 234-I — A-324 / A-328 ---------------------------------------------
    t234i = TraceBuilder('Fee for furnishing a revised return u/s 234-I')
    fee234i = 0
    is_revised = m['filingStatus']['returnFileSec'] == 17
    if is_revised and filing_date > K['s234I']['afterDate']:
        fee234i = K['s234I']['feeUpTo5Lakh'] if ctx['totalIncome'] <= K['s234I']['incomeThreshold'] else K['s234I']['feeAbove5Lakh']
        t234i.add(f"Revised return filed after {K['s234I']['afterDate']}").add('Total income', ctx['totalIncome']).result(
            'Fee u/s 234-I', fee234i
        )
    else:
        t234i.result('Not applicable — no fee u/s 234-I', 0)

    # User overrides for D7, D8, D10 (the portal makes these editable).
    interest234a_override = m['taxLiability'].get('interest234AOverride')
    interest234b_override = m['taxLiability'].get('interest234BOverride')
    fee234f_override = m['taxLiability'].get('fee234FOverride')
    interest234a = interest234a_computed if interest234a_override is None else interest234a_override
    interest234b = interest234b_computed if interest234b_override is None else interest234b_override
    fee234f = fee234f_computed if fee234f_override is None else fee234f_override

    # A-28
    total = interest234a + interest234b + interest234c + fee234f + fee234i

    return {
        'interest234A': interest234a,
        'interest234AComputed': interest234a_computed,
        'interest234B': interest234b,
        'interest234BComputed': interest234b_computed,
        'interest234C': interest234c,
        'fee234F': fee234f,
        'fee234FComputed': fee234f_computed,
        'fee234I': fee234i,
        'total': total,
        'trace234A': t234a.build(),
        'trace234B': t234b.build(),
        'trace234C': t234c.build(),
        'trace234F': t234f.build(),
        'trace234I': t234i.build(),
    }


def old_regime_basic_exemption(m):
    K = Constants
    lim = K['regimes']['OLD']['basicExemptionLimits']
    age = age_on(m['personalInfo']['dob'], K['seniorCitizen']['ageReferenceDate'])
    if age is not None and age >= K['seniorCitizen']['superSeniorMinAge']:
        return lim['superSenior']
    if age is not None and age >= K['seniorCitizen']['seniorMinAge']:
        return lim['senior']
    return lim['default']
