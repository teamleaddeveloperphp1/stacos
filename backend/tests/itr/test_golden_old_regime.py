"""The old-regime golden test case (addendum §4 to the build prompt).

SUNITA RAO - AAAPS1234R - 139(1) return, old regime, senior citizen (age 62
on the AY 2026-27 reference date). Mirrors test_golden.py's structure and
discipline exactly: every expected figure below was computed once via the
engine itself against this fixture and then pinned as a literal -- if any of
them change, the build is wrong, not the test.

Unlike the new-regime golden case (total income ~2.6L, well under the
₹5,00,000 87A ceiling), this fixture lands above ₹5,00,000 so old-regime
87A is correctly ₹0 -- the complementary boundary case.
"""

from itr.engine.compute import compute
from itr.engine.validate import validate
from itr.model_blank import blank_return_model

OLD_REGIME_GOLDEN_EXPECTED = {
    'grossTotalIncome': 862000,
    'totalDeductions': 200000,
    'totalIncome': 662000,
    'taxPayableOnTotalIncome': 42400,
    'rebate87A': 0,
    'educationCess': 1696,
    'totalTaxAndCess': 44096,
    'interest234A': 0,
    'interest234B': 0,
    'interest234C': 0,
    'fee234F': 0,
    'fee234I': 0,
    'totalTaxFeeAndInterest': 44100,
    'totalTaxesPaid': 60000,
    'refundDue': 15900,
    'incomeFromSalary': 850000,
    'incomeOthSrc': 12000,
    'deductionUs16': 50000,
    'netSalary': 900000,
    'grossSalary': 900000,
    'hraEligibleExemption': 160000,
    'age': 62,
    'isSeniorCitizenA13': True,
}


def old_regime_golden_model():
    m = blank_return_model('tenant-demo', 'golden-old-1')

    m['personalInfo']['firstName'] = 'SUNITA'
    m['personalInfo']['middleName'] = ''
    m['personalInfo']['lastName'] = 'RAO'
    m['personalInfo']['pan'] = 'AAAPS1234R'
    m['personalInfo']['dob'] = '1963-06-15'  # senior citizen (age >= 60)
    m['personalInfo']['aadhaar'] = '123456784639'
    m['personalInfo']['aadhaarMatchesProfile'] = True
    m['personalInfo']['aadhaarLinkedToPan'] = True
    m['personalInfo']['employerCategory'] = 'OTH'

    m['personalInfo']['contact'] = {
        'primaryMobileCountryCode': '91',
        'primaryMobile': '9199366400',
        'secondaryMobileCountryCode': '',
        'secondaryMobile': '',
        'primaryEmail': 'sunita.rao@example.com',
        'secondaryEmail': '',
    }

    m['personalInfo']['primaryAddress'] = {
        'flatDoorBuilding': 'FLAT 5',
        'premiseBuildingName': 'GREEN PARK',
        'roadStreet': 'MG ROAD',
        'areaLocality': 'INDIRANAGAR',
        'townCityDistrict': 'BENGALURU',
        'stateCode': '29',  # Karnataka
        'countryCode': '91',
        'pinCode': '560038',
        'zipCode': '',
    }
    m['personalInfo']['secondaryAddressSameAsPrimary'] = 'Y'

    # 139(1), before the due date -- old regime selectable.
    m['filingStatus']['returnFileSec'] = 11
    m['filingStatus']['optOutOfNewRegime'] = 'Y'
    m['filingStatus']['filingDate'] = '2026-07-15'
    m['filingStatus']['representativeAssesseeFlag'] = 'N'
    m['filingStatus']['seventhProviso139'] = 'N'

    # Salary: gross 9,00,000.
    m['income']['salary17_1'] = 900000
    m['income']['perquisites17_2'] = 0
    m['income']['profitsInLieu17_3'] = 0

    # Schedule 10(13A) -- HRA 1,80,000 received, metro, rent 2,00,000.
    m['income']['hra10_13A'] = {
        'placeOfWork': '1',  # metro
        'actualHraReceived': 180000,
        'actualRentPaid': 200000,
        'salary17_1': 900000,
        'basicSalary': 400000,
        'dearnessAllowance': 0,
    }

    m['income']['otherSources'] = [
        {'id': 'os-1', 'nature': 'SAV', 'otherNatureDescription': '', 'amount': 12000, 'dividendQuarterly': None},
    ]

    # 80C at the ₹1,50,000 aggregate cap.
    m['deductions']['s80C'] = 150000
    m['deductions']['schedule80C'] = [{'id': 'c80c-1', 'identificationNo': 'PPFACCT123', 'amount': 150000}]

    # 80D at the senior self/family cap (₹50,000: ₹45,000 premium + ₹5,000 preventive).
    m['deductions']['s80D'] = 50000
    m['deductions']['schedule80D']['selfFamilySeniorFlag'] = 'Y'
    m['deductions']['schedule80D']['selfFamilySenior'] = {
        'healthInsurancePremium': 45000,
        'insurers': [{'insurerName': 'LIC HEALTH', 'policyNumber': 'POL12345', 'amount': 45000}],
        'preventiveHealthCheckup': 5000,
        'medicalExpenditure': 0,
    }

    m['taxPaid']['tds1'] = [
        {
            'id': 'tds1-1',
            'tan': 'MUMS27065D',
            'deductorName': 'ACME PVT LTD',
            'incomeChargeableSalary': 900000,
            'totalTaxDeducted': 60000,
        }
    ]

    m['bankAccounts'] = [
        {
            'id': 'bank-1',
            'ifsc': 'HDFC0000123',
            'bankName': 'HDFC BANK',
            'accountNumber': '50100123456790',
            'accountType': 'SB',
            'nominateForRefund': True,
        }
    ]

    m['verification'] = {
        'assesseeVerName': 'SUNITA RAO',
        'fatherName': 'RAMESH RAO',
        'assesseeVerPan': 'AAAPS1234R',
        'capacity': 'S',
        'place': 'BENGALURU',
        'date': '2026-07-15',
    }

    for k in m['screenStatus']:
        m['screenStatus'][k] = 'CONFIRMED'

    return m


def test_old_regime_golden_case():
    m = old_regime_golden_model()
    c = compute(m)

    assert c['regime'] == 'OLD'
    assert c['age'] == OLD_REGIME_GOLDEN_EXPECTED['age']
    assert c['isSeniorCitizenA13'] == OLD_REGIME_GOLDEN_EXPECTED['isSeniorCitizenA13']
    assert c['grossTotalIncome'] == OLD_REGIME_GOLDEN_EXPECTED['grossTotalIncome']
    assert c['totalDeductions'] == OLD_REGIME_GOLDEN_EXPECTED['totalDeductions']
    assert c['totalIncome'] == OLD_REGIME_GOLDEN_EXPECTED['totalIncome']
    assert c['tax']['taxPayableOnTotalIncome'] == OLD_REGIME_GOLDEN_EXPECTED['taxPayableOnTotalIncome']
    assert c['tax']['rebate87A'] == OLD_REGIME_GOLDEN_EXPECTED['rebate87A']
    assert c['tax']['educationCess'] == OLD_REGIME_GOLDEN_EXPECTED['educationCess']
    assert c['tax']['totalTaxAndCess'] == OLD_REGIME_GOLDEN_EXPECTED['totalTaxAndCess']
    assert c['interest']['interest234A'] == OLD_REGIME_GOLDEN_EXPECTED['interest234A']
    assert c['interest']['interest234B'] == OLD_REGIME_GOLDEN_EXPECTED['interest234B']
    assert c['interest']['interest234C'] == OLD_REGIME_GOLDEN_EXPECTED['interest234C']
    assert c['interest']['fee234F'] == OLD_REGIME_GOLDEN_EXPECTED['fee234F']
    assert c['interest']['fee234I'] == OLD_REGIME_GOLDEN_EXPECTED['fee234I']
    assert c['totalTaxFeeAndInterest'] == OLD_REGIME_GOLDEN_EXPECTED['totalTaxFeeAndInterest']
    assert c['taxesPaid']['total'] == OLD_REGIME_GOLDEN_EXPECTED['totalTaxesPaid']
    assert c['refundDue'] == OLD_REGIME_GOLDEN_EXPECTED['refundDue']
    assert c['salary']['incomeFromSalary'] == OLD_REGIME_GOLDEN_EXPECTED['incomeFromSalary']
    assert c['otherSources']['netIncomeOthSrc'] == OLD_REGIME_GOLDEN_EXPECTED['incomeOthSrc']
    assert c['salary']['deductionUs16'] == OLD_REGIME_GOLDEN_EXPECTED['deductionUs16']
    assert c['salary']['netSalary'] == OLD_REGIME_GOLDEN_EXPECTED['netSalary']
    assert c['salary']['grossSalary'] == OLD_REGIME_GOLDEN_EXPECTED['grossSalary']
    assert c['hra']['eligibleExemption'] == OLD_REGIME_GOLDEN_EXPECTED['hraEligibleExemption']


def test_old_regime_golden_case_validates_clean():
    m = old_regime_golden_model()
    c = compute(m)
    report = validate(m, tier=3, computed=c)

    assert report.ruleErrors == []
    assert report.errors == []
    assert report.ok is True
