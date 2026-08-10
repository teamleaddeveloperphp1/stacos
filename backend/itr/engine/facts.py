"""The fact bag: the read-only view of (model + computed) that rule expressions
are evaluated against.

Ported 1:1 from itr1-module/packages/core/src/engine/facts.ts.

Names here are the public vocabulary of the rule registry. Adding a rule must
not require a code change, so this bag is deliberately generous: every figure
a CBDT rule could reference is exposed, pre-derived.
"""

from itr.engine.constants import CONSTANTS
from itr.util.num import n, sum_by

Constants = CONSTANTS

SECTION_KEYS = list(Constants['chapterVIA']['sections'].keys())


def build_facts(m, c):
    f = {}

    # ---- regime & identity -------------------------------------------------
    f['regime'] = c['regime']
    f['isOldRegime'] = c['regime'] == 'OLD'
    f['isNewRegime'] = c['regime'] == 'NEW'
    f['optOutOfNewRegime'] = m['filingStatus']['optOutOfNewRegime']
    f['status'] = m['personalInfo']['status']
    f['isIndividual'] = m['personalInfo']['status'] == 'INDIVIDUAL'
    f['employerCategory'] = m['personalInfo']['employerCategory']
    f['employerCategoryPresent'] = bool(m['personalInfo']['employerCategory'])

    f['pan'] = (m['personalInfo']['pan'] or '').upper()
    f['panFourthChar'] = (m['personalInfo']['pan'] or '').upper()[3:4]
    f['verificationPan'] = (m['verification']['assesseeVerPan'] or '').upper()
    f['assesseeName'] = ' '.join(
        x for x in [m['personalInfo']['firstName'], m['personalInfo']['middleName'], m['personalInfo']['lastName']] if x
    ).strip()
    f['firstName'] = m['personalInfo']['firstName']
    f['lastName'] = m['personalInfo']['lastName']
    f['dob'] = m['personalInfo']['dob']
    f['dateOfFormation'] = m['personalInfo']['dateOfFormation']
    f['aadhaar'] = m['personalInfo']['aadhaar']
    f['aadhaarPresent'] = len(m['personalInfo']['aadhaar'] or '') == 12
    f['aadhaarLinkedToPan'] = m['personalInfo']['aadhaarLinkedToPan']
    aadhaar_matches = m['personalInfo'].get('aadhaarMatchesProfile')
    f['aadhaarMatchesProfile'] = True if aadhaar_matches is None else aadhaar_matches
    f['age'] = c['age']
    f['isSeniorA13'] = c['isSeniorCitizenA13']
    f['isSeniorForTTB'] = c['isSeniorForTTB']
    f['isSuperSenior'] = c['isSuperSenior']
    f['armedForcesJoiningDate'] = m['personalInfo']['armedForcesJoiningDate']

    # ---- contact & addresses ----------------------------------------------
    ct = m['personalInfo']['contact']
    f['primaryMobile'] = ct['primaryMobile']
    f['secondaryMobile'] = ct['secondaryMobile']
    f['primaryEmail'] = (ct['primaryEmail'] or '').lower()
    f['secondaryEmail'] = (ct['secondaryEmail'] or '').lower()
    f['secondaryAddressSameAsPrimary'] = m['personalInfo']['secondaryAddressSameAsPrimary']
    f['secondaryAddressProvided'] = _address_has_content(dict(m['personalInfo']['secondaryAddress']))
    f['secondaryAddressDiffersFromPrimary'] = not _addresses_equal(
        dict(m['personalInfo']['primaryAddress']), dict(m['personalInfo']['secondaryAddress'])
    )

    # ---- representative assessee ------------------------------------------
    rep = m['filingStatus']['representativeAssessee']
    f['repFlag'] = m['filingStatus']['representativeAssesseeFlag']
    f['repProvided'] = bool(rep)
    f['repName'] = (rep or {}).get('name', '') if rep else ''
    f['repEmail'] = ((rep or {}).get('email', '') or '').lower() if rep else ''
    f['repMobile'] = (rep or {}).get('mobile', '') if rep else ''
    f['repPan'] = ((rep or {}).get('pan', '') or '').upper() if rep else ''
    f['verificationCapacity'] = m['verification']['capacity']
    f['repEmailClashes'] = bool(
        rep
        and rep.get('email')
        and rep['email'].lower() in [x.lower() for x in [ct['primaryEmail'], ct['secondaryEmail']] if x]
    )
    f['repMobileClashes'] = bool(
        rep and rep.get('mobile') and rep['mobile'] in [x for x in [ct['primaryMobile'], ct['secondaryMobile']] if x]
    )

    # ---- filing status -----------------------------------------------------
    fs = m['filingStatus']
    f['filingSection'] = fs['returnFileSec']
    f['isSection139_1'] = fs['returnFileSec'] == 11
    f['isSection139_4'] = fs['returnFileSec'] == 12
    f['isSection139_5'] = fs['returnFileSec'] == 17
    f['isSection139_9'] = fs['returnFileSec'] == 18
    f['isSection142_1'] = fs['returnFileSec'] == 13
    f['isSection148'] = fs['returnFileSec'] == 14
    f['isSection119_2b'] = fs['returnFileSec'] == 20
    f['isReturnUnder139'] = fs['returnFileSec'] in [11, 12, 17]
    f['origReturnFileSec'] = fs['origReturnFileSec']
    f['origReturnWas139_4'] = fs['origReturnFileSec'] == 12
    f['origReturnWas142_1'] = fs['origReturnFileSec'] == 13
    f['proceedingsInitiatedUs148'] = fs['proceedingsInitiatedUs148']
    f['a23ResponsesMatch'] = fs['a23ResponsesCurrent'] == fs['a23ResponsesOriginal']
    f['filingDate'] = fs['filingDate']
    f['dueDate139_1'] = Constants['dueDates']['us139_1']
    f['isFiledAfterDueDate'] = c['isBelatedOrLate']
    f['seventhProviso139'] = fs['seventhProviso139']

    # ---- B1 salary ---------------------------------------------------------
    s = c['salary']
    f['salary17_1'] = s['salary17_1']
    f['perquisites17_2'] = s['perquisites17_2']
    f['profitsInLieu17_3'] = s['profitsInLieu17_3']
    f['grossSalary'] = s['grossSalary']
    f['exemptAllowancesTotal'] = s['totalExemptAllowances']
    f['netSalary'] = s['netSalary']
    f['standardDeduction16ia'] = s['standardDeduction16ia']
    f['entertainmentAllowance16ii'] = s['entertainmentAllowance16ii']
    f['entertainmentAllowance16iiEntered'] = n(m['income']['entertainmentAllowance16ii'])
    f['professionalTax16iii'] = s['professionalTax16iii']
    f['professionalTax16iiiEntered'] = n(m['income']['professionalTax16iii'])
    f['deductionUs16'] = s['deductionUs16']
    f['incomeFromSalary'] = s['incomeFromSalary']
    f['hasSalaryIncome'] = s['grossSalary'] > 0
    f['employerRows'] = [dict(e) for e in m['income']['employers']]

    allowance_rows = [{'nature': r['nature'], 'amount': n(r['amount'])} for r in m['income']['exemptAllowances']]
    f['exemptAllowanceRows'] = allowance_rows
    f['allowanceNatures'] = [r['nature'] for r in allowance_rows if r['nature']]

    def allw(nature):
        return sum_by([r for r in allowance_rows if r['nature'] == nature], lambda r: r['amount'])

    f['allw10_5'] = allw('10(5)')
    f['allw10_6'] = allw('10(6)')
    f['allw10_7'] = allw('10(7)')
    f['allw10_10'] = allw('10(10)')
    f['allw10_10A'] = allw('10(10A)')
    f['allw10_10AA'] = allw('10(10AA)')
    f['allw10_10Bi'] = allw('10(10B)(i)')
    f['allw10_10Bii'] = allw('10(10B)(ii)')
    f['allw10_10C'] = allw('10(10C)')
    f['allw10_10CC'] = allw('10(10CC)')
    f['allw10_13A'] = allw('10(13A)')
    f['allw10_14i'] = allw('10(14)(i)')
    f['allw10_14ii'] = allw('10(14)(ii)')
    f['allw10_14i115BAC'] = allw('10(14)(i)(115BAC)')
    f['allw10_14ii115BAC'] = allw('10(14)(ii)(115BAC)')
    f['allw10_17'] = allw('10(17)')
    f['allwEIC'] = allw('EIC')
    f['allowance10_10BOr10CCount'] = len(
        [x for x in ['10(10B)(i)', '10(10B)(ii)', '10(10C)'] if any(r['nature'] == x for r in allowance_rows)]
    )
    f['gratuityCeiling'] = s['allowanceCeilings'].get('10(10)')

    # Schedule 10(13A)
    hra_src = m['income']['hra10_13A']
    f['hraScheduleFilled'] = hra_src['actualHraReceived'] > 0 or hra_src['actualRentPaid'] > 0 or hra_src['basicSalary'] > 0
    f['hraActualReceived'] = c['hra']['actualHraReceived']
    f['hraRentLess10Percent'] = c['hra']['rentPaidLess10PercentOfSalary']
    f['hra40Or50Percent'] = c['hra']['salary40Or50Percent']
    f['hraEligibleExemption'] = c['hra']['eligibleExemption']
    f['hraBasicPlusDaPlusHra'] = c['hra']['basicPlusDaPlusHra']
    f['hraScheduleSalary17_1'] = n(hra_src['salary17_1'])

    # ---- B2 house property -------------------------------------------------
    assessee_pan = (m['personalInfo']['pan'] or '').upper()
    hp_rows = []
    for i, p in enumerate(c['houseProperty']['properties']):
        src = m['income']['properties'][i] if i < len(m['income']['properties']) else None
        is_co_owned = bool(src) and src.get('coOwned') == 'YES'
        own_share = n(src.get('assesseeSharePercent')) if (src and is_co_owned) else 100
        co_owner_shares = [n(x['sharePercent']) for x in (src.get('coOwners') if src else []) or []]
        co_owner_pans = [
            (x.get('pan') or '').upper() for x in ((src.get('coOwners') if src else []) or []) if (x.get('pan') or '').upper()
        ]
        local_taxes_entered = n(src.get('localTaxes')) if src else 0
        gross_rent_entered = n(src.get('grossRent')) if src else 0
        rent_not_realized_entered = n(src.get('rentNotRealized')) if src else 0
        interest_entered_raw = n(src.get('interestOnBorrowedCapital')) if src else 0
        is_self_occupied = bool(src) and src.get('propertyType') == 'S'
        is_let_out_or_deemed = bool(src) and src.get('propertyType') in ('L', 'D')

        row = dict(p)
        row.update(
            {
                'propertyType': src.get('propertyType', '') if src else '',
                'isSelfOccupied': is_self_occupied,
                'isLetOut': bool(src) and src.get('propertyType') == 'L',
                'isDeemedLetOut': bool(src) and src.get('propertyType') == 'D',
                'coOwned': src.get('coOwned', '') if src else '',
                'assesseeSharePercent': own_share,
                'coOwnerPans': co_owner_pans,
                'coOwnerShares': co_owner_shares,
                'totalShare': own_share + p['coOwnersShareTotal'],
                'localTaxesEntered': local_taxes_entered,
                'grossRentEntered': gross_rent_entered,
                'rentNotRealizedEntered': rent_not_realized_entered,
                'schedule24BRowCount': len(src.get('schedule24B') or []) if src else 0,
                'interestEnteredRaw': interest_entered_raw,
                # --- derived per-row rule flags (one per CBDT assertion) -------------
                'thirtyPercentMismatch': p['thirtyPercent']
                != round(Constants['houseProperty']['standardDeductionRate'] * p['annualValueOfShare']),
                'localTaxWithoutRent': local_taxes_entered > 0 and gross_rent_entered <= 0,
                'letOutWithoutRent': is_let_out_or_deemed and gross_rent_entered <= 0,
                'annualValueMismatch': p['balanceAnnualValue'] != max(0, p['grossRent'] - p['totalUnrealizedAndTax']),
                'incomeMismatch': p['incomeOfHP'] != p['annualValueOfShare'] - p['totalDeduct'] + p['arrears'],
                'selfOccupiedInterestOverCap': is_self_occupied
                and p['interestCap'] is not None
                and interest_entered_raw > p['interestCap'],
                'selfOccupiedWithLocalTax': is_self_occupied and local_taxes_entered > 0,
                'interestWithoutSchedule24B': interest_entered_raw > 0 and len(src.get('schedule24B') or []) == 0
                if src
                else interest_entered_raw > 0,
                'interestScheduleMismatch': interest_entered_raw > 0 and interest_entered_raw != p['schedule24BTotal'],
                'coOwnedShareTotalNot100': is_co_owned and own_share + p['coOwnersShareTotal'] != 100,
                'annualValueShareMismatch': p['annualValueOfShare']
                != round(p['balanceAnnualValue'] * own_share / 100),
                'zeroShareWithInterest': is_co_owned and own_share == 0 and interest_entered_raw > 0,
                'total1dMismatch': p['totalUnrealizedAndTax'] != p['rentNotRealized'] + p['localTaxes'],
                'total1iMismatch': p['totalDeduct'] != p['thirtyPercent'] + p['interestAllowed'],
                'coOwnerPanClash': assessee_pan in co_owner_pans and assessee_pan != '',
                'coOwnedOwnShareNotBelow100': is_co_owned and own_share >= 100,
                'coOwnerShareOutOfRange': is_co_owned and any(s <= 0 or s >= 100 for s in co_owner_shares),
                'notCoOwnedShareNot100': bool(src)
                and src.get('coOwned') == 'NO'
                and n(src.get('assesseeSharePercent')) != 100
                and n(src.get('assesseeSharePercent')) != 0,
                'rentNotRealizedOverGrossRent': rent_not_realized_entered > gross_rent_entered,
            }
        )
        hp_rows.append(row)
    f['hpRows'] = hp_rows
    f['hasHouseProperty'] = len(hp_rows) > 0
    f['hpHeadIncome'] = c['houseProperty']['headIncome']
    f['hpIncomeForGti'] = c['houseProperty']['incomeForGti']
    f['hpHasLoss'] = c['houseProperty']['headIncome'] < 0
    f['hpTotalInterestClaimed'] = sum(p['interestEnteredRaw'] for p in hp_rows)
    f['hpTotalSchedule24B'] = sum(p['schedule24BTotal'] for p in hp_rows)
    f['hpAnyInterestClaimed'] = any(p['interestEnteredRaw'] > 0 for p in hp_rows)
    f['hpAnyMissingType'] = any(not p['propertyType'] for p in hp_rows)
    f['sched24BRows'] = [dict(r) for p in m['income']['properties'] for r in p['schedule24B']]
    f['sched24BLenderKeys'] = [
        f"{r['lenderName']}|{r['loanAccountNo']}" for p in m['income']['properties'] for r in p['schedule24B']
    ]

    # ---- B3 other sources --------------------------------------------------
    os_ = c['otherSources']
    f['othSrcRows'] = os_['rows']
    f['othSrcNatures'] = [r['nature'] for r in os_['rows'] if r['nature']]
    f['othSrcGrossTotal'] = os_['grossTotal']
    f['savingsInterest'] = os_['savingsInterest']
    f['depositInterest'] = os_['depositInterest']
    f['interestIncomeTotal'] = os_['interestIncomeTotal']
    f['familyPension'] = os_['familyPension']
    f['dividendTotal'] = os_['dividendTotal']
    f['dividendQuarterlyTotal'] = sum(os_['dividendQuarterly'].values())
    f['deduction57iia'] = os_['deduction57iia']
    f['deduction57iiaEntered'] = os_['deduction57iia']
    f['deduction57iiaCap'] = os_['deduction57iiaCap']
    f['incomeOthSrc'] = os_['netIncomeOthSrc']

    # ---- exempt income -----------------------------------------------------
    ex_rows = [
        {
            'category': r['category'],
            'subCategory': r['subCategory'],
            'description': r['description'],
            'amount': n(r['amount']),
        }
        for r in m['income']['exemptIncome']
    ]
    f['exemptIncomeRows'] = ex_rows
    f['exemptIncomeSubCategories'] = [r['subCategory'] for r in ex_rows if r['subCategory']]
    f['exemptIncomeTotal'] = c['exemptIncomeTotal']
    f['exemptIncomeRowSum'] = sum_by(ex_rows, lambda r: r['amount'])
    f['agriExemptIncome'] = c['agriExemptIncome']
    f['exemptIncome10_32'] = sum_by([r for r in ex_rows if r['subCategory'] == '10(32)'], lambda r: r['amount'])

    # ---- LTCG 112A ---------------------------------------------------------
    f['ltcg112A'] = c['ltcg112A']
    f['ltcg112ASale'] = c['ltcg112ASubRows']['sale']
    f['ltcg112ACost'] = c['ltcg112ASubRows']['cost']

    # ---- totals ------------------------------------------------------------
    f['grossTotalIncome'] = c['grossTotalIncome']
    f['grossTotalIncomeInclLtcg'] = c['grossTotalIncomeInclLtcg']
    f['totalDeductions'] = c['totalDeductions']
    f['totalIncome'] = c['totalIncome']
    f['totalIncomeUnrounded'] = c['totalIncomeUnrounded']
    f['totalIncomeExclLtcg'] = c['totalIncomeExclLtcg']

    # ---- Chapter VI-A ------------------------------------------------------
    for key in SECTION_KEYS:
        d = c['deductions']['bySection'].get(key)
        f[f'u{key}'] = d['entered'] if d else 0
        f[f'e{key}'] = d['eligible'] if d else 0
        f[f'cap{key}'] = d['cap'] if d else None
    f['aggregate80CGroup'] = c['deductions']['aggregate80CGroup']
    f['aggregate80CGroupEntered'] = (
        n(m['deductions']['s80C']) + n(m['deductions']['s80CCC']) + n(m['deductions']['s80CCD1'])
    )
    f['chapterVIATotal'] = c['totalDeductions']
    f['chapterVIATotalBeforeGti'] = c['deductions']['totalBeforeGtiRestriction']

    # Schedules behind the deductions
    f['sched80CRows'] = [dict(r) for r in m['deductions']['schedule80C']]
    f['sched80CTotal'] = c['deductions']['schedule80CTotal']
    f['sched80CCCRows'] = [dict(r) for r in m['deductions']['pensionContribution80CCC']]
    f['sched80CCCTotal'] = c['deductions']['schedule80CCCTotal']
    f['pranNumbers'] = [x for x in m['deductions']['pranNumbers'] if x]
    f['pranProvided'] = len([x for x in m['deductions']['pranNumbers'] if x]) > 0

    d80 = c['deductions']['schedule80D']
    f['sched80DFilled'] = _schedule_80d_has_content(m)
    f['sched80DSelfFlag'] = m['deductions']['schedule80D']['selfFamilySeniorFlag']
    f['sched80DParentsFlag'] = m['deductions']['schedule80D']['parentsSeniorFlag']
    f['sched80D1aRaw'] = d80['selfFamily']['rawTotal']
    f['sched80D1a'] = d80['selfFamily']['deduction']
    f['sched80D1bRaw'] = d80['selfFamilySenior']['rawTotal']
    f['sched80D1b'] = d80['selfFamilySenior']['deduction']
    f['sched80D2aRaw'] = d80['parents']['rawTotal']
    f['sched80D2a'] = d80['parents']['deduction']
    f['sched80D2bRaw'] = d80['parentsSenior']['rawTotal']
    f['sched80D2b'] = d80['parentsSenior']['deduction']
    f['sched80DPreventiveTotal'] = d80['preventiveTotalAcrossBlocks']
    f['sched80DEligible'] = d80['eligibleAmountOfDeduction']
    f['sched80D1aInsurance'] = d80['selfFamily']['healthInsurance']
    f['sched80D1aInsurersTotal'] = d80['selfFamily']['insurersTotal']
    f['sched80D1bInsurance'] = d80['selfFamilySenior']['healthInsurance']
    f['sched80D1bInsurersTotal'] = d80['selfFamilySenior']['insurersTotal']
    f['sched80D2aInsurance'] = d80['parents']['healthInsurance']
    f['sched80D2aInsurersTotal'] = d80['parents']['insurersTotal']
    f['sched80D2bInsurance'] = d80['parentsSenior']['healthInsurance']
    f['sched80D2bInsurersTotal'] = d80['parentsSenior']['insurersTotal']
    f['sched80D1aInsurers'] = [dict(r) for r in m['deductions']['schedule80D']['selfFamily']['insurers']]
    f['sched80D1bInsurers'] = [dict(r) for r in m['deductions']['schedule80D']['selfFamilySenior']['insurers']]
    f['sched80D2aInsurers'] = [dict(r) for r in m['deductions']['schedule80D']['parents']['insurers']]
    f['sched80D2bInsurers'] = [dict(r) for r in m['deductions']['schedule80D']['parentsSenior']['insurers']]

    f['sched80DDNature'] = m['deductions']['schedule80DD']['natureOfDisability']
    f['sched80DDFilled'] = _schedule_80ddu_has_content(m['deductions']['schedule80DD'])
    f['sched80DDAmount'] = n(m['deductions']['schedule80DD']['amount'])
    f['sched80DDForm10IA'] = m['deductions']['schedule80DD']['form10IAFiled']
    f['sched80UNature'] = m['deductions']['schedule80U']['natureOfDisability']
    f['sched80UFilled'] = _schedule_80ddu_has_content(m['deductions']['schedule80U'])
    f['sched80UAmount'] = n(m['deductions']['schedule80U']['amount'])
    f['sched80UForm10IA'] = m['deductions']['schedule80U']['form10IAFiled']

    f['s80DDBUsrType'] = m['deductions']['s80DDBUsrType']
    f['s80DDBDisease'] = m['deductions']['s80DDBDisease']

    # Loan schedules carry a `sanctionDateOutOfWindow` flag so the date-window
    # rules (A-230, A-232, A-252) read as a row-count assertion.
    def loan_rows(rows, window=None):
        out = []
        for r in rows:
            r2 = dict(r)
            if window:
                r2['sanctionDateOutOfWindow'] = (
                    not r.get('dateOfLoan') or r['dateOfLoan'] < window['sanctionFrom'] or r['dateOfLoan'] > window['sanctionTo']
                )
            else:
                r2['sanctionDateOutOfWindow'] = False
            out.append(r2)
        return out

    f['sched80ERows'] = loan_rows(m['deductions']['schedule80E'])
    f['sched80ETotal'] = c['deductions']['schedule80ETotal']
    f['sched80EERows'] = loan_rows(m['deductions']['schedule80EE'], Constants['chapterVIA']['s80EE'])
    f['sched80EETotal'] = c['deductions']['schedule80EETotal']
    f['sched80EEALenderKeys'] = [f"{r['lenderName']}|{r['loanAccountNo']}" for r in m['deductions']['schedule80EEA']]
    f['sched80EELenderKeys'] = [f"{r['lenderName']}|{r['loanAccountNo']}" for r in m['deductions']['schedule80EE']]
    f['sched80EEARows'] = loan_rows(m['deductions']['schedule80EEA'], Constants['chapterVIA']['s80EEA'])
    f['sched80EEATotal'] = c['deductions']['schedule80EEATotal']
    f['sched80EEBRows'] = loan_rows(m['deductions']['schedule80EEB'], Constants['chapterVIA']['s80EEB'])
    f['sched80EEBTotal'] = c['deductions']['schedule80EEBTotal']
    f['stampDutyValue80EEA'] = n(m['deductions']['stampDutyValue80EEA'])

    g = c['deductions']['schedule80G']
    f['sched80GFilled'] = (
        len(m['deductions']['schedule80G']['don100Percent'])
        + len(m['deductions']['schedule80G']['don50PercentNoApprReqd'])
        + len(m['deductions']['schedule80G']['don100PercentApprReqd'])
        + len(m['deductions']['schedule80G']['don50PercentApprReqd'])
        > 0
    )
    f['sched80GTotalCash'] = g['totalCash']
    f['sched80GTotalOtherMode'] = g['totalOtherMode']
    f['sched80GTotal'] = g['total']
    f['sched80GTotalEligible'] = g['totalEligible']
    f['sched80GBlockA'] = g['blocks']['Don100Percent']
    f['sched80GBlockB'] = g['blocks']['Don50PercentNoApprReqd']
    f['sched80GBlockC'] = g['blocks']['Don100PercentApprReqd']
    f['sched80GBlockD'] = g['blocks']['Don50PercentApprReqd']
    all_donees = (
        [{**r, 'block': 'A'} for r in m['deductions']['schedule80G']['don100Percent']]
        + [{**r, 'block': 'B'} for r in m['deductions']['schedule80G']['don50PercentNoApprReqd']]
        + [{**r, 'block': 'C'} for r in m['deductions']['schedule80G']['don100PercentApprReqd']]
        + [{**r, 'block': 'D'} for r in m['deductions']['schedule80G']['don50PercentApprReqd']]
    )
    f['sched80GDoneeRows'] = [
        {
            **r,
            'pan': (r.get('pan') or '').upper(),
            'donationTotal': n(r['donationCash']) + n(r['donationOtherMode']),
            'hasBothModes': n(r['donationCash']) > 0 and n(r['donationOtherMode']) > 0,
            'missingRefForNonCash': n(r['donationOtherMode']) > 0 and (not r.get('ifsc') or not r.get('transactionRefNo')),
        }
        for r in all_donees
    ]
    f['sched80GDoneePans'] = [(r.get('pan') or '').upper() for r in all_donees if (r.get('pan') or '').upper()]
    f['sched80GPansAcrossBlocks'] = [(r.get('pan') or '').upper() for r in all_donees]
    f['sched80GBlockTotalsSumEligible'] = (
        g['blocks']['Don100Percent']['totalEligible']
        + g['blocks']['Don50PercentNoApprReqd']['totalEligible']
        + g['blocks']['Don100PercentApprReqd']['totalEligible']
        + g['blocks']['Don50PercentApprReqd']['totalEligible']
    )
    f['sched80GBlockTotalsSum'] = (
        g['blocks']['Don100Percent']['total']
        + g['blocks']['Don50PercentNoApprReqd']['total']
        + g['blocks']['Don100PercentApprReqd']['total']
        + g['blocks']['Don50PercentApprReqd']['total']
    )

    f['sched80GGARows'] = [
        {**r, 'pan': (r.get('pan') or '').upper(), 'donationTotal': n(r['donationCash']) + n(r['donationOtherMode'])}
        for r in m['deductions']['schedule80GGA']
    ]
    f['sched80GGAPans'] = [
        (r.get('pan') or '').upper() for r in m['deductions']['schedule80GGA'] if (r.get('pan') or '').upper()
    ]
    f['sched80GGACashPans'] = [
        (r.get('pan') or '').upper()
        for r in m['deductions']['schedule80GGA']
        if n(r['donationCash']) > 0 and (r.get('pan') or '').upper()
    ]
    f['sched80GGATotalCash'] = c['deductions']['schedule80GGA']['totalCash']
    f['sched80GGATotalOtherMode'] = c['deductions']['schedule80GGA']['totalOtherMode']
    f['sched80GGATotal'] = c['deductions']['schedule80GGA']['total']
    f['sched80GGAEligible'] = c['deductions']['schedule80GGA']['eligible']
    f['sched80GGAFilled'] = len(m['deductions']['schedule80GGA']) > 0
    f['sched80GGAAnyCashAbove2000'] = any(
        n(r['donationCash']) > Constants['chapterVIA']['s80GGA']['cashDonationCap']
        for r in m['deductions']['schedule80GGA']
    )

    f['sched80GGCRows'] = [
        {**r, 'donationTotal': n(r['donationCash']) + n(r['donationOtherMode'])}
        for r in m['deductions']['schedule80GGC']
    ]
    f['sched80GGCTotalCash'] = c['deductions']['schedule80GGC']['totalCash']
    f['sched80GGCTotalOtherMode'] = c['deductions']['schedule80GGC']['totalOtherMode']
    f['sched80GGCTotal'] = c['deductions']['schedule80GGC']['total']
    f['sched80GGCEligible'] = c['deductions']['schedule80GGC']['eligible']
    f['sched80GGCFilled'] = len(m['deductions']['schedule80GGC']) > 0
    f['sched80GGCDates'] = [r['donationDate'] for r in m['deductions']['schedule80GGC']]
    f['sched80GGCAllDatesInWindow'] = all(
        bool(r.get('donationDate'))
        and Constants['chapterVIA']['s80GGC']['contributionFrom'] <= r['donationDate'] <= Constants['chapterVIA']['s80GGC']['contributionTo']
        for r in m['deductions']['schedule80GGC']
    )

    f['form10BAFiled'] = m['deductions']['form10BAFiled']
    f['form10BAAckNo'] = m['deductions']['form10BAAckNo']

    # ---- Screen 4 tax paid -------------------------------------------------
    cls = Constants['advanceTaxClassification']
    f['tds1Rows'] = [dict(r) for r in m['taxPaid']['tds1']]
    f['tds2Rows'] = [
        {
            **r,
            'tdsOverClaimed': n(r['tdsClaimedThisYear']) > n(r['taxDeducted']),
            'yearMissing': n(r['tdsClaimedThisYear']) > 0 and (not r.get('deductedYear') or r['deductedYear'] == '0'),
        }
        for r in m['taxPaid']['tds2']
    ]
    f['tds3Rows'] = [
        {
            **r,
            'tdsOverClaimed': n(r['tdsClaimedThisYear']) > n(r['taxDeducted']),
            'yearMissing': n(r['tdsClaimedThisYear']) > 0 and (not r.get('deductedYear') or r['deductedYear'] == '0'),
        }
        for r in m['taxPaid']['tds3']
    ]
    f['tcsRows'] = [
        {
            **r,
            'tcsOverClaimed': n(r['tcsClaimedThisYear']) > n(r['taxCollected']),
            'yearMissing': n(r['tcsClaimedThisYear']) > 0 and (not r.get('collectedYear') or r['collectedYear'] == '0'),
        }
        for r in m['taxPaid']['tcs']
    ]
    f['challanRows'] = [
        {
            **r,
            'isAdvanceTax': bool(r.get('dateOfDeposit'))
            and cls['advanceTaxFrom'] <= r['dateOfDeposit'] <= cls['advanceTaxTo'],
            'isSelfAssessmentTax': bool(r.get('dateOfDeposit')) and r['dateOfDeposit'] > cls['selfAssessmentAfter'],
        }
        for r in m['taxPaid']['challans']
    ]
    f['tds1Total'] = c['taxesPaid']['tds1']
    f['tds2Total'] = c['taxesPaid']['tds2']
    f['tds3Total'] = c['taxesPaid']['tds3']
    f['totalTds'] = c['taxesPaid']['totalTds']
    f['tcsTotal'] = c['taxesPaid']['tcs']
    f['advanceTax'] = c['taxesPaid']['advanceTax']
    f['selfAssessmentTax'] = c['taxesPaid']['selfAssessmentTax']
    f['totalTaxesPaid'] = c['taxesPaid']['total']
    f['tds192'] = c['taxesPaid']['tds192']
    f['tds1SalaryTotal'] = sum_by(m['taxPaid']['tds1'], lambda r: r['incomeChargeableSalary'])
    f['tds2Sections'] = [r['tdsSection'] for r in m['taxPaid']['tds2'] if r.get('tdsSection')]
    f['tds3Sections'] = [r['tdsSection'] for r in m['taxPaid']['tds3'] if r.get('tdsSection')]
    f['tds2HeadsWithoutIncome'] = [
        r['deductorName']
        for r in m['taxPaid']['tds2']
        if n(r['tdsClaimedThisYear']) > 0 and n(r['grossReceipt']) > 0 and not _head_is_offered(r.get('headOfIncome'), c)
    ]
    f['tds3HeadsWithoutIncome'] = [
        r['nameOfTenant']
        for r in m['taxPaid']['tds3']
        if n(r['tdsClaimedThisYear']) > 0 and n(r['grossReceipt']) > 0 and not _head_is_offered(r.get('headOfIncome'), c)
    ]
    f['tdsCreditWithoutIncomeDeductors'] = list(f['tds2HeadsWithoutIncome']) + list(f['tds3HeadsWithoutIncome'])

    # ---- Screen 5 tax liability -------------------------------------------
    t = c['tax']
    f['taxPayableOnTotalIncome'] = t['taxPayableOnTotalIncome']
    f['rebate87A'] = t['rebate87A']
    f['taxPayableAfterRebate'] = t['taxPayableAfterRebate']
    f['educationCess'] = t['educationCess']
    f['totalTaxAndCess'] = t['totalTaxAndCess']
    f['relief89'] = t['relief89']
    f['form10EFiled'] = m['taxLiability']['form10EFiled']
    f['balanceTaxAfterRelief'] = t['balanceTaxAfterRelief']
    f['interest234A'] = c['interest']['interest234A']
    f['interest234B'] = c['interest']['interest234B']
    f['interest234C'] = c['interest']['interest234C']
    f['fee234F'] = c['interest']['fee234F']
    f['fee234I'] = c['interest']['fee234I']
    f['fee234IComputed'] = c['interest']['fee234I']
    f['totalInterestAndFee'] = c['interest']['total']
    f['totalTaxFeeAndInterest'] = c['totalTaxFeeAndInterest']
    f['refundDue'] = c['refundDue']
    f['balanceTaxPayable'] = c['balanceTaxPayable']
    f['taxLiabilityComputedAndPaid'] = c['totalTaxFeeAndInterest'] > 0 and c['taxesPaid']['total'] > 0
    f['anyTaxesPaidDisclosed'] = c['taxesPaid']['total'] > 0
    f['anyIncomeDisclosed'] = c['grossTotalIncomeInclLtcg'] != 0

    # ---- bank --------------------------------------------------------------
    f['bankAccounts'] = [dict(b) for b in m['bankAccounts']]
    f['bankAccountCount'] = len(m['bankAccounts'])
    f['nominatedAccountCount'] = len([b for b in m['bankAccounts'] if b.get('nominateForRefund')])
    # A-107 covers Bank Details, Schedule 80G and Schedule 80GGC IFSCs alike;
    # a donee/GGC row with no IFSC entered (a cash donation) has nothing to
    # verify and must not count against the assertion.
    f['anyIfscUnverified'] = (
        any(b.get('ifscVerified') is not True for b in m['bankAccounts'])
        or any(r.get('ifsc') and r.get('ifscVerified') is not True for r in all_donees)
        or any(r.get('ifsc') and r.get('ifscVerified') is not True for r in m['deductions']['schedule80GGC'])
    )
    f['allIfscKeys'] = [x for x in (
        [b.get('ifsc') for b in m['bankAccounts']]
        + [r.get('ifsc') for r in all_donees]
        + [r.get('ifsc') for r in m['deductions']['schedule80GGC']]
    ) if x]

    # ---- constants exposed to expressions ---------------------------------
    f['K'] = Constants

    return f


def _head_is_offered(head, c):
    h = (head or '').upper()
    if h == 'SALARY':
        return c['salary']['grossSalary'] > 0
    if h in ('HP', 'HOUSE_PROPERTY'):
        return c['houseProperty']['headIncome'] != 0
    if h in ('OS', 'OTHER_SOURCES'):
        return c['otherSources']['grossTotal'] > 0
    if h == 'EXEMPT':
        return c['exemptIncomeTotal'] > 0
    # An unclassified head cannot be reconciled, so treat it as not offered.
    return False


def _address_has_content(a):
    return any(k != 'countryCode' and str(v if v is not None else '').strip() != '' for k, v in a.items())


_ADDRESS_COMPARE_KEYS = (
    'flatDoorBuilding',
    'premiseBuildingName',
    'roadStreet',
    'areaLocality',
    'townCityDistrict',
    'stateCode',
    'countryCode',
    'pinCode',
    'zipCode',
)


def _addresses_equal(a, b):
    return all(
        str(a.get(k) if a.get(k) is not None else '').strip().upper() == str(b.get(k) if b.get(k) is not None else '').strip().upper()
        for k in _ADDRESS_COMPARE_KEYS
    )


def _schedule_80d_has_content(m):
    s = m['deductions']['schedule80D']
    blocks = [s['selfFamily'], s['selfFamilySenior'], s['parents'], s['parentsSenior']]
    return bool(
        s['selfFamilySeniorFlag'] == 'Y'
        or s['parentsSeniorFlag'] == 'Y'
        or any(
            n(b['healthInsurancePremium']) > 0
            or n(b['preventiveHealthCheckup']) > 0
            or n(b['medicalExpenditure']) > 0
            or len(b['insurers']) > 0
            for b in blocks
        )
    )


def _schedule_80ddu_has_content(s):
    return bool(s['natureOfDisability']) and bool(s['typeOfDisability']) and n(s['amount']) > 0
