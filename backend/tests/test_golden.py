"""The golden test case (build prompt section 12).

ANSHAL THAKUR - AHKPT5171E - belated return u/s 139(4) - new regime.
Every expected figure below is taken from the reference screenshots of the
government portal. If any of them change, the build is wrong -- not the test.

Ported from itr1-module/packages/core/test/fixtures/golden.ts.
"""

from itr1.engine.compute import compute
from itr1.engine.validate import validate
from itr1.model_blank import blank_return_model

GOLDEN_EXPECTED = {
    'grossTotalIncome': 263366,
    'totalDeductions': 0,
    'totalIncome': 263370,
    'taxPayableOnTotalIncome': 0,
    'rebate87A': 0,
    'educationCess': 0,
    'totalTaxAndCess': 0,
    'interest234A': 0,
    'interest234B': 0,
    'interest234C': 0,
    'fee234F': 0,
    'fee234I': 0,
    'totalTaxFeeAndInterest': 0,
    'totalTaxesPaid': 24500,
    'refundDue': 24500,
    'incomeFromSalary': 255000,
    'incomeOthSrc': 8366,
    'deductionUs16': 75000,
    'netSalary': 330000,
    'grossSalary': 330000,
}


def golden_model():
    m = blank_return_model('tenant-demo', 'golden-1')

    m['personalInfo']['firstName'] = 'ANSHAL'
    m['personalInfo']['middleName'] = ''
    m['personalInfo']['lastName'] = 'THAKUR'
    m['personalInfo']['pan'] = 'AHKPT5171E'
    m['personalInfo']['dob'] = '1986-12-28'
    m['personalInfo']['aadhaar'] = '123456784638'
    m['personalInfo']['aadhaarMatchesProfile'] = True
    m['personalInfo']['aadhaarLinkedToPan'] = True
    m['personalInfo']['employerCategory'] = 'OTH'

    m['personalInfo']['contact'] = {
        'primaryMobileCountryCode': '91',
        'primaryMobile': '9199366399',
        'secondaryMobileCountryCode': '',
        'secondaryMobile': '',
        'primaryEmail': 'anshal.thakur@gmail.com',
        'secondaryEmail': '',
    }

    m['personalInfo']['primaryAddress'] = {
        'flatDoorBuilding': 'FLAT NO 202',
        'premiseBuildingName': 'SUNDARAM BLOCK',
        'roadStreet': 'SINHA LIBRARY ROAD',
        'areaLocality': 'MANSAROVAR GARDEN',
        'townCityDistrict': 'PATNA',
        'stateCode': '05',  # Bihar
        'countryCode': '91',  # India
        'pinCode': '800001',
        'zipCode': '',
    }
    # A-338: a secondary address is mandatory. "Same as primary" satisfies it.
    m['personalInfo']['secondaryAddressSameAsPrimary'] = 'Y'

    # Belated return. A-151 therefore disables the old regime and locks the
    # opt-out radio to "No" -> NEW REGIME.
    m['filingStatus']['returnFileSec'] = 12
    m['filingStatus']['optOutOfNewRegime'] = 'N'
    m['filingStatus']['filingDate'] = '2026-08-07'
    m['filingStatus']['representativeAssesseeFlag'] = 'N'
    m['filingStatus']['seventhProviso139'] = 'N'

    # Salary: gross 3,30,000, no exempt allowances.
    m['income']['salary17_1'] = 330000
    m['income']['perquisites17_2'] = 0
    m['income']['profitsInLieu17_3'] = 0

    # Other sources 8,366 (bank interest).
    m['income']['otherSources'] = [
        {
            'id': 'os-1',
            'nature': 'SAV',
            'otherNatureDescription': '',
            'amount': 8366,
            'dividendQuarterly': None,
        }
    ]

    # Schedule TDS1 -- Form 16.
    m['taxPaid']['tds1'] = [
        {
            'id': 'tds1-1',
            'tan': 'MUMS27065D',
            'deductorName': 'SKORYDOV SYSTEMS PRIVATE LIMITED',
            'incomeChargeableSalary': 330000,
            'totalTaxDeducted': 24500,
        }
    ]

    m['bankAccounts'] = [
        {
            'id': 'bank-1',
            'ifsc': 'HDFC0000123',
            'bankName': 'HDFC BANK',
            'accountNumber': '50100123456789',
            'accountType': 'SB',
            'nominateForRefund': True,
            'ifscVerified': True,
            'ifscVerificationNote': 'HDFC BANK -- PATNA MAIN',
        }
    ]

    m['verification'] = {
        'assesseeVerName': 'ANSHAL THAKUR',
        'fatherName': 'RAJESH THAKUR',
        'assesseeVerPan': 'AHKPT5171E',
        'capacity': 'S',
        'place': 'PATNA',
        'date': '2026-08-07',
    }

    for k in m['screenStatus']:
        m['screenStatus'][k] = 'CONFIRMED'

    return m


def test_golden_case():
    m = golden_model()
    c = compute(m)

    assert c['grossTotalIncome'] == GOLDEN_EXPECTED['grossTotalIncome']
    assert c['totalDeductions'] == GOLDEN_EXPECTED['totalDeductions']
    assert c['totalIncome'] == GOLDEN_EXPECTED['totalIncome']
    assert c['tax']['taxPayableOnTotalIncome'] == GOLDEN_EXPECTED['taxPayableOnTotalIncome']
    assert c['tax']['rebate87A'] == GOLDEN_EXPECTED['rebate87A']
    assert c['tax']['educationCess'] == GOLDEN_EXPECTED['educationCess']
    assert c['tax']['totalTaxAndCess'] == GOLDEN_EXPECTED['totalTaxAndCess']
    assert c['interest']['interest234A'] == GOLDEN_EXPECTED['interest234A']
    assert c['interest']['interest234B'] == GOLDEN_EXPECTED['interest234B']
    assert c['interest']['interest234C'] == GOLDEN_EXPECTED['interest234C']
    assert c['interest']['fee234F'] == GOLDEN_EXPECTED['fee234F']
    assert c['interest']['fee234I'] == GOLDEN_EXPECTED['fee234I']
    assert c['totalTaxFeeAndInterest'] == GOLDEN_EXPECTED['totalTaxFeeAndInterest']
    assert c['taxesPaid']['total'] == GOLDEN_EXPECTED['totalTaxesPaid']
    assert c['refundDue'] == GOLDEN_EXPECTED['refundDue']
    assert c['salary']['incomeFromSalary'] == GOLDEN_EXPECTED['incomeFromSalary']
    assert c['otherSources']['netIncomeOthSrc'] == GOLDEN_EXPECTED['incomeOthSrc']
    assert c['salary']['deductionUs16'] == GOLDEN_EXPECTED['deductionUs16']
    assert c['salary']['netSalary'] == GOLDEN_EXPECTED['netSalary']
    assert c['salary']['grossSalary'] == GOLDEN_EXPECTED['grossSalary']


def test_golden_case_validates_clean():
    m = golden_model()
    c = compute(m)
    report = validate(m, tier=3, computed=c)

    assert report.ruleErrors == []
    assert report.errors == []
    assert report.ok is True
