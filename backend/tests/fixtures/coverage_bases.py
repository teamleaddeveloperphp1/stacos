"""A spread of base returns, chosen so that between them every rule's
`appliesWhen` becomes true for at least one base. The coverage harness picks
the first base under which a rule is live, then falsifies its assertion.

Ported 1:1 from itr1-module/packages/core/test/fixtures/coverage-bases.ts
AND bases.ts (bases.ts's shared builders -- newRegimeBase / oldRegimeBase /
seniorOldRegimeBase / emptyBase / housePropertyBase -- have no separate
Python module of their own; the coverage suite is their only Python
consumer, so they live here rather than being split into a second file).

`COVERAGE_BASES` matches the TS `NamedBase[]` shape: a list of plain dicts
with 'name' (str) and 'build' (zero-arg callable returning a fresh
ReturnModel dict) keys, since Python has no interface/type to declare for
this and a dict is the most direct analogue of the TS object literal.
"""

from itr.model_blank import blank_return_model
from tests.itr.test_golden import golden_model

# ---------------------------------------------------------------------------
# bases.ts
# ---------------------------------------------------------------------------


def new_regime_base():
    """New regime, belated 139(4) -- the golden case."""
    return golden_model()


def old_regime_base():
    """Old regime, filed 139(1) on 2026-07-15 (before the due date), CG
    employee, salaried with enough income that the Chapter VI-A caps
    actually bite."""
    m = golden_model()
    m['filingStatus']['returnFileSec'] = 11
    m['filingStatus']['filingDate'] = '2026-07-15'
    m['filingStatus']['optOutOfNewRegime'] = 'Y'
    m['personalInfo']['employerCategory'] = 'CGOV'
    m['income']['salary17_1'] = 1200000
    m['income']['perquisites17_2'] = 0
    m['income']['profitsInLieu17_3'] = 0
    m['income']['otherSources'] = [
        {'id': 'os-1', 'nature': 'SAV', 'otherNatureDescription': '', 'amount': 12000, 'dividendQuarterly': None},
        {'id': 'os-2', 'nature': 'IFD', 'otherNatureDescription': '', 'amount': 40000, 'dividendQuarterly': None},
    ]
    m['taxPaid']['tds1'] = [
        {
            'id': 'tds1-1',
            'tan': 'MUMS27065D',
            'deductorName': 'SKORYDOV SYSTEMS PRIVATE LIMITED',
            'incomeChargeableSalary': 1200000,
            'totalTaxDeducted': 120000,
        }
    ]
    return m


def senior_old_regime_base():
    """Old regime, senior citizen (DOB 01.04.1966 -- the A-13 boundary)."""
    m = old_regime_base()
    m['personalInfo']['dob'] = '1966-04-01'
    return m


def empty_base():
    """A minimal model with nothing filled in -- exercises the "mandatory"
    rules."""
    return blank_return_model('tenant-test', 'empty-1')


def house_property_base():
    """Old regime with a let-out house property and a Schedule 24(b) row."""
    m = old_regime_base()
    m['income']['properties'] = [
        {
            'id': 'hp-1',
            'address': {
                'flatDoorBuilding': '12 GREEN PARK',
                'townCityDistrict': 'PATNA',
                'stateCode': '05',
                'countryCode': '91',
                'pinCode': '800001',
            },
            'propertyOwner': 'SE',
            'propertyOwnerOther': '',
            'coOwned': 'NO',
            'assesseeSharePercent': 100,
            'coOwners': [],
            'propertyType': 'L',
            'tenants': [],
            'grossRent': 300000,
            'rentNotRealized': 0,
            'localTaxes': 20000,
            'interestOnBorrowedCapital': 150000,
            'schedule24B': [
                {
                    'id': 'l24b-1',
                    'loanTakenFrom': 'B',
                    'lenderName': 'HDFC BANK',
                    'loanAccountNo': 'HL123456',
                    'dateOfLoan': '2018-06-01',
                    'totalLoanAmount': 3000000,
                    'loanOutstandingAmount': 2000000,
                    'interestPaid': 150000,
                }
            ],
            'arrearsUnrealisedRentReceived': 0,
        }
    ]
    return m


# ---------------------------------------------------------------------------
# coverage-bases.ts
# ---------------------------------------------------------------------------


def _with_all_schedules():
    m = house_property_base()
    d = m['deductions']

    d['s80C'] = 100000
    d['schedule80C'] = [
        {'id': 'c1', 'typeOfIdentifier': 'LIC', 'identificationNo': 'LIC-11223', 'amount': 100000},
    ]
    d['s80CCC'] = 20000
    d['pensionContribution80CCC'] = [
        {'id': 'pc1', 'typeOfIdentifier': 'PRAN', 'nameOfIdentifier': '110022003300', 'amount': 20000},
    ]
    d['s80CCD1'] = 30000
    d['s80CCD1B'] = 50000
    d['pranNumbers'] = ['110022003300']
    d['s80CCD2'] = 100000

    d['s80D'] = 25000
    d['schedule80D'] = {
        'selfFamilySeniorFlag': 'N',
        'selfFamily': {
            'healthInsurancePremium': 22000,
            'insurers': [{'id': 'i1', 'insurerName': 'STAR HEALTH', 'policyNo': 'P-9911', 'amount': 22000}],
            'preventiveHealthCheckup': 3000,
            'medicalExpenditure': 0,
        },
        'selfFamilySenior': {
            'healthInsurancePremium': 0,
            'insurers': [],
            'preventiveHealthCheckup': 0,
            'medicalExpenditure': 0,
        },
        'parentsSeniorFlag': 'Y',
        'parents': {'healthInsurancePremium': 0, 'insurers': [], 'preventiveHealthCheckup': 0, 'medicalExpenditure': 0},
        'parentsSenior': {
            'healthInsurancePremium': 40000,
            'insurers': [{'id': 'i2', 'insurerName': 'NIVA BUPA', 'policyNo': 'P-7722', 'amount': 40000}],
            'preventiveHealthCheckup': 2000,
            'medicalExpenditure': 0,
        },
    }

    d['s80DD'] = 75000
    d['schedule80DD'] = {
        'natureOfDisability': '1',
        'typeOfDisability': '1',
        'amount': 75000,
        'dependentType': '1',
        'dependentPan': 'BHKPT5171F',
        'dependentAadhaar': '',
        'form10IAFiled': True,
        'form10IAAckNo': '100000000000001',
        'udidNo': 'UDID000000001',
    }
    d['s80U'] = 75000
    d['schedule80U'] = {
        'natureOfDisability': '1',
        'typeOfDisability': '1',
        'amount': 75000,
        'form10IAFiled': True,
        'form10IAAckNo': '100000000000002',
        'udidNo': 'UDID000000002',
    }

    d['s80DDB'] = 40000
    d['s80DDBUsrType'] = '1'
    d['s80DDBDisease'] = 'a'

    d['s80E'] = 60000
    d['schedule80E'] = [
        {
            'id': 'e1',
            'loanTakenFrom': 'B',
            'lenderName': 'SBI',
            'loanAccountNo': 'EDU-101',
            'dateOfLoan': '2020-07-01',
            'totalLoanAmount': 800000,
            'loanOutstandingAmount': 500000,
            'interest': 60000,
        }
    ]

    d['s80EE'] = 50000
    d['schedule80EE'] = [
        {
            'id': 'ee1',
            'loanTakenFrom': 'B',
            'lenderName': 'HDFC BANK',
            'loanAccountNo': 'HL123456',
            'dateOfLoan': '2016-09-01',
            'totalLoanAmount': 3000000,
            'loanOutstandingAmount': 2000000,
            'interest': 50000,
        }
    ]

    d['s80EEB'] = 150000
    d['schedule80EEB'] = [
        {
            'id': 'eeb1',
            'loanTakenFrom': 'B',
            'lenderName': 'ICICI BANK',
            'loanAccountNo': 'EV-5566',
            'dateOfLoan': '2021-05-01',
            'totalLoanAmount': 900000,
            'loanOutstandingAmount': 600000,
            'interest': 150000,
            'vehicleRegNo': 'BR01AB1234',
        }
    ]

    d['s80G'] = 50000
    d['schedule80G'] = {
        'don100Percent': [
            {
                'id': 'g1',
                'name': 'PRIME MINISTER NATIONAL RELIEF FUND',
                'pan': 'AAAGP0001A',
                'arnNo': '',
                'address': {
                    'flatDoorBuilding': 'SOUTH BLOCK',
                    'townCityDistrict': 'NEW DELHI',
                    'stateCode': '09',
                    'pinCode': '110011',
                },
                'donationCash': 0,
                'donationOtherMode': 50000,
                'transactionRefNo': 'NEFT-778899',
                'ifsc': 'SBIN0000691',
            }
        ],
        'don50PercentNoApprReqd': [],
        'don100PercentApprReqd': [],
        'don50PercentApprReqd': [],
    }

    d['s80GGA'] = 10000
    d['schedule80GGA'] = [
        {
            'id': 'gga1',
            'relevantClause': '80GGA2a',
            'name': 'INDIAN INSTITUTE OF SCIENCE',
            'pan': 'AAATI0002B',
            'address': {
                'flatDoorBuilding': 'CV RAMAN ROAD',
                'townCityDistrict': 'BENGALURU',
                'stateCode': '15',
                'pinCode': '560012',
            },
            'donationCash': 0,
            'donationOtherMode': 10000,
        }
    ]

    d['s80GGC'] = 15000
    d['schedule80GGC'] = [
        {
            'id': 'ggc1',
            'donationDate': '2025-08-14',
            'politicalPartyName': 'A REGISTERED POLITICAL PARTY',
            'politicalPartyPan': 'AAAAP0003C',
            'donationCash': 0,
            'donationOtherMode': 15000,
            'transactionRefNo': 'RTGS-112233',
            'ifsc': 'HDFC0000123',
        }
    ]

    d['s80TTA'] = 10000

    m['income']['exemptAllowances'] = [
        {'id': 'a1', 'nature': '10(10)', 'amount': 100000},
        {'id': 'a2', 'nature': '10(13A)', 'amount': 60000},
    ]
    m['income']['hra10_13A'] = {
        'placeOfWork': '2',
        'actualHraReceived': 60000,
        'actualRentPaid': 180000,
        'salary17_1': 1200000,
        'basicSalary': 300000,
        'dearnessAllowance': 0,
    }
    # A-269 requires the claimed 10(13A) to equal the schedule's eligible amount.
    m['income']['exemptAllowances'][1]['amount'] = 60000

    m['income']['exemptIncome'] = [
        {'id': 'ei1', 'category': 'AGRI', 'subCategory': '10(1)', 'description': 'Agricultural income', 'amount': 5000},
    ]

    m['income']['otherSources'] = [
        {'id': 'os-1', 'nature': 'SAV', 'otherNatureDescription': '', 'amount': 12000, 'dividendQuarterly': None},
        {'id': 'os-2', 'nature': 'IFD', 'otherNatureDescription': '', 'amount': 40000, 'dividendQuarterly': None},
        {'id': 'os-3', 'nature': 'FAP', 'otherNatureDescription': '', 'amount': 60000, 'dividendQuarterly': None},
        {
            'id': 'os-4',
            'nature': 'DIV',
            'otherNatureDescription': '',
            'amount': 20000,
            'dividendQuarterly': {
                'Upto15Of6': 4000,
                'Upto15Of9': 4000,
                'Up16Of9To15Of12': 4000,
                'Up16Of12To15Of3': 4000,
                'Up16Of3To31Of3': 4000,
            },
        },
    ]

    m['income']['ltcg112A'] = {'totalSaleConsideration': 300000, 'totalCostOfAcquisition': 200000}

    return m


def _with_all_tax_paid():
    """Every tax-paid schedule populated."""
    m = old_regime_base()
    m['taxPaid']['tds2'] = [
        {
            'id': 'tds2-1',
            'tanOrPan': 'DELM12345F',
            'deductorName': 'A BANK LIMITED',
            'grossReceipt': 40000,
            'deductedYear': '2025',
            'taxDeducted': 4000,
            'tdsClaimedThisYear': 4000,
            'tdsSection': '94A',
            'headOfIncome': 'OS',
        }
    ]
    m['taxPaid']['tds3'] = [
        {
            'id': 'tds3-1',
            'panOfTenant': 'BHKPT5171F',
            'aadhaarOfTenant': '',
            'nameOfTenant': 'A TENANT',
            'grossReceipt': 300000,
            'deductedYear': '2025',
            'taxDeducted': 15000,
            'tdsClaimedThisYear': 15000,
            'tdsSection': '94-IB',
            'headOfIncome': 'HP',
        }
    ]
    m['taxPaid']['tcs'] = [
        {
            'id': 'tcs-1',
            'tan': 'BLRC12345E',
            'collectorName': 'A COLLECTOR',
            'taxCollected': 2000,
            'collectedYear': '2025',
            'totalTcs': 2000,
            'tcsClaimedThisYear': 2000,
        }
    ]
    m['taxPaid']['challans'] = [
        {'id': 'chl-1', 'bsrCode': '0510308', 'dateOfDeposit': '2025-06-14', 'challanSerialNo': '00123', 'amount': 20000},
        {'id': 'chl-2', 'bsrCode': '0510308', 'dateOfDeposit': '2026-06-20', 'challanSerialNo': '00124', 'amount': 5000},
    ]
    # Both TDS3 rows above use a valid schema section code.
    m['taxPaid']['tds3'][0]['tdsSection'] = '4-IB'
    m['income']['properties'] = house_property_base()['income']['properties']
    return m


def _revised_late():
    """Revised return filed after 31.12.2026 -- makes A-324 / A-328 live."""
    m = new_regime_base()
    m['filingStatus']['returnFileSec'] = 17
    m['filingStatus']['origReturnFileSec'] = 11
    m['filingStatus']['origReturnAckNo'] = '123456789012345'
    m['filingStatus']['origReturnFiledDate'] = '2026-07-01'
    m['filingStatus']['filingDate'] = '2027-01-15'
    return m


def _representative_and_notice():
    """Representative assessee, 139(9), and the notice-driven paths."""
    m = new_regime_base()
    m['filingStatus']['returnFileSec'] = 18
    m['filingStatus']['filedInResponseToNotice'] = True
    m['filingStatus']['noticeSection'] = 18
    m['filingStatus']['noticeNo'] = 'CPC/2026/139(9)/0001'
    m['filingStatus']['noticeDate'] = '2026-09-10'
    m['filingStatus']['a23ResponsesOriginal'] = 'YES|NO|NO'
    m['filingStatus']['a23ResponsesCurrent'] = 'YES|NO|NO'
    m['filingStatus']['representativeAssesseeFlag'] = 'Y'
    m['filingStatus']['representativeAssessee'] = {
        'name': 'RAMESH GUPTA',
        'pan': 'CHKPG5171G',
        'email': 'ramesh.gupta@example.com',
        'mobileCountryCode': '91',
        'mobile': '9812345678',
        'capacity': 'Guardian',
        'address': {},
    }
    m['verification']['capacity'] = 'R'
    return m


def _new_regime_with_schedules():
    """New regime with every schedule wrongly present -- makes the A-15x
    family live."""
    m = _with_all_schedules()
    m['filingStatus']['optOutOfNewRegime'] = 'N'
    m['filingStatus']['returnFileSec'] = 12
    m['filingStatus']['filingDate'] = '2026-08-07'
    return m


def _with_80gg():
    """80GG claimed instead of HRA."""
    m = old_regime_base()
    m['deductions']['s80GG'] = 60000
    m['deductions']['form10BAFiled'] = True
    m['deductions']['form10BAAckNo'] = '100000000000003'
    return m


def _with_80cch():
    """80CCH for a Central Government Agniveer."""
    m = old_regime_base()
    m['personalInfo']['employerCategory'] = 'CGOV'
    m['personalInfo']['armedForcesJoiningDate'] = '2010-06-01'
    m['deductions']['s80CCH'] = 100000
    return m


def _with_80eea():
    """80EEA with its own stamp-duty and window constraints."""
    m = _with_all_schedules()
    m['deductions']['s80EE'] = 0
    m['deductions']['schedule80EE'] = []
    m['deductions']['s80EEA'] = 150000
    m['deductions']['stampDutyValue80EEA'] = 4000000
    m['deductions']['schedule80EEA'] = [
        {
            'id': 'eea1',
            'loanTakenFrom': 'B',
            'lenderName': 'HDFC BANK',
            'loanAccountNo': 'HL123456',
            'dateOfLoan': '2020-09-01',
            'totalLoanAmount': 3000000,
            'loanOutstandingAmount': 2000000,
            'interest': 150000,
        }
    ]
    return m


def _pensioner_old_regime():
    """Old regime, pensioner employer category -- makes A-2 and A-116 live."""
    m = old_regime_base()
    m['personalInfo']['employerCategory'] = 'PE'
    m['deductions']['s80CCD1'] = 50000
    m['deductions']['pranNumbers'] = ['110022003300']
    return m


def _other_employer_old_regime():
    """Old regime, "Others" employer -- makes A-4 and A-58 live."""
    m = old_regime_base()
    m['personalInfo']['employerCategory'] = 'OTH'
    m['deductions']['s80CCD2'] = 60000
    m['income']['entertainmentAllowance16ii'] = 0
    return m


def _all_80g_blocks():
    """All four Schedule 80G blocks populated -- makes A-85 to A-87 live."""
    m = old_regime_base()

    def donee(id_, pan, amount):
        return {
            'id': id_,
            'name': f'DONEE {id_.upper()}',
            'pan': pan,
            'arnNo': 'AAAAA-12345',
            'address': {
                'flatDoorBuilding': '1 CHARITY LANE',
                'townCityDistrict': 'NEW DELHI',
                'stateCode': '09',
                'pinCode': '110011',
            },
            'donationCash': 0,
            'donationOtherMode': amount,
            'transactionRefNo': f'NEFT-{id_}',
            'ifsc': 'SBIN0000691',
        }

    m['deductions']['schedule80G'] = {
        'don100Percent': [donee('g1', 'AAAGP0001A', 20000)],
        'don50PercentNoApprReqd': [donee('g2', 'AAAGP0002B', 20000)],
        'don100PercentApprReqd': [donee('g3', 'AAAGP0003C', 20000)],
        'don50PercentApprReqd': [donee('g4', 'AAAGP0004D', 20000)],
    }
    m['deductions']['s80G'] = 50000
    return m


def _schedule_80d_other_blocks():
    """Schedule 80D with the 1b and 2a blocks used -- makes
    A-179/180/235/236/257/258 live."""
    m = old_regime_base()
    m['deductions']['s80D'] = 75000
    m['deductions']['schedule80D'] = {
        'selfFamilySeniorFlag': 'Y',
        'selfFamily': {'healthInsurancePremium': 0, 'insurers': [], 'preventiveHealthCheckup': 0, 'medicalExpenditure': 0},
        'selfFamilySenior': {
            'healthInsurancePremium': 45000,
            'insurers': [{'id': 'i1', 'insurerName': 'STAR HEALTH', 'policyNo': 'P-1111', 'amount': 45000}],
            'preventiveHealthCheckup': 2000,
            'medicalExpenditure': 0,
        },
        'parentsSeniorFlag': 'N',
        'parents': {
            'healthInsurancePremium': 22000,
            'insurers': [{'id': 'i2', 'insurerName': 'NIVA BUPA', 'policyNo': 'P-2222', 'amount': 22000}],
            'preventiveHealthCheckup': 3000,
            'medicalExpenditure': 0,
        },
        'parentsSenior': {'healthInsurancePremium': 0, 'insurers': [], 'preventiveHealthCheckup': 0, 'medicalExpenditure': 0},
    }
    return m


def _schedule_80d_not_claiming():
    """Schedule 80D with both "not claiming" flags -- makes A-182 and A-183
    live."""
    m = old_regime_base()
    m['deductions']['s80D'] = 0
    m['deductions']['schedule80D']['selfFamilySeniorFlag'] = 'S'
    m['deductions']['schedule80D']['parentsSeniorFlag'] = 'P'
    return m


def _severe_disability():
    """Severe disability under both 80DD and 80U -- makes A-200 and A-204
    live."""
    m = old_regime_base()
    m['deductions']['s80DD'] = 125000
    m['deductions']['schedule80DD'] = {
        'natureOfDisability': '2',
        'typeOfDisability': '2',
        'amount': 125000,
        'dependentType': '1',
        'dependentPan': 'BHKPT5171F',
        'dependentAadhaar': '',
        'form10IAFiled': True,
        'form10IAAckNo': '100000000000001',
        'udidNo': 'UDID000000001',
    }
    m['deductions']['s80U'] = 125000
    m['deductions']['schedule80U'] = {
        'natureOfDisability': '2',
        'typeOfDisability': '2',
        'amount': 125000,
        'form10IAFiled': True,
        'form10IAAckNo': '100000000000002',
        'udidNo': 'UDID000000002',
    }
    return m


def _original_142():
    """Original return u/s 142(1) -- makes A-126 live."""
    m = old_regime_base()
    m['filingStatus']['origReturnFileSec'] = 13
    m['filingStatus']['returnFileSec'] = 13
    m['filingStatus']['origReturnAckNo'] = '123456789012345'
    return m


def _proceedings_148():
    """Proceedings initiated u/s 148 -- makes A-152 live."""
    m = old_regime_base()
    m['filingStatus']['proceedingsInitiatedUs148'] = True
    m['filingStatus']['returnFileSec'] = 14
    return m


def _new_regime_hp_loss():
    """New regime with a house property loss -- makes A-160 live."""
    m = house_property_base()
    m['filingStatus']['optOutOfNewRegime'] = 'N'
    m['filingStatus']['returnFileSec'] = 12
    p = m['income']['properties'][0]
    p['propertyType'] = 'L'
    p['grossRent'] = 60000
    p['localTaxes'] = 0
    p['interestOnBorrowedCapital'] = 400000
    p['schedule24B'][0]['interestPaid'] = 400000
    return m


def _with_10_10cc():
    """10(10CC) claimed against perquisites -- makes A-177 live."""
    m = old_regime_base()
    m['income']['perquisites17_2'] = 50000
    m['income']['exemptAllowances'] = [{'id': 'a1', 'nature': '10(10CC)', 'amount': 20000}]
    return m


def _with_judge_exempt_income():
    """Judge's exempt income for a CG employee -- makes A-270 live."""
    m = old_regime_base()
    m['personalInfo']['employerCategory'] = 'CGOV'
    m['income']['exemptAllowances'] = [{'id': 'a1', 'nature': 'EIC', 'amount': 50000}]
    return m


def _revised_after_belated():
    """139(5) after a 139(4) original -- makes A-189 live."""
    m = new_regime_base()
    m['filingStatus']['returnFileSec'] = 17
    m['filingStatus']['origReturnFileSec'] = 12
    m['filingStatus']['origReturnAckNo'] = '123456789012345'
    m['filingStatus']['origReturnFiledDate'] = '2026-09-01'
    m['filingStatus']['filingDate'] = '2026-10-01'
    return m


def _high_income_new_regime():
    """Total income above the Rs.12,70,590 marginal-relief cut-off -- makes
    A-191 live."""
    m = new_regime_base()
    m['income']['salary17_1'] = 1600000
    m['income']['otherSources'] = []
    m['taxPaid']['tds1'] = [
        {
            'id': 'tds1-1',
            'tan': 'MUMS27065D',
            'deductorName': 'SKORYDOV SYSTEMS PRIVATE LIMITED',
            'incomeChargeableSalary': 1525000,
            'totalTaxDeducted': 150000,
        }
    ]
    return m


def _revised_late_high_income():
    """Revised return, filed late, income above Rs.5 lakh -- makes A-328
    live."""
    m = new_regime_base()
    m['filingStatus']['returnFileSec'] = 17
    m['filingStatus']['origReturnFileSec'] = 11
    m['filingStatus']['origReturnAckNo'] = '123456789012345'
    m['filingStatus']['origReturnFiledDate'] = '2026-07-01'
    m['filingStatus']['filingDate'] = '2027-01-15'
    m['income']['salary17_1'] = 1000000
    m['income']['otherSources'] = []
    m['taxPaid']['tds1'][0]['incomeChargeableSalary'] = 925000
    m['taxPaid']['tds1'][0]['totalTaxDeducted'] = 50000
    return m


def _miscellaneous_flags():
    """A distinct secondary address, a date of formation, and relief u/s 89."""
    m = old_regime_base()
    m['personalInfo']['secondaryAddressSameAsPrimary'] = 'N'
    m['personalInfo']['secondaryAddress'] = {
        **m['personalInfo']['primaryAddress'],
        'flatDoorBuilding': 'FLAT NO 909',
        'areaLocality': 'BORING ROAD',
    }
    m['personalInfo']['dateOfFormation'] = '2000-01-01'
    m['taxLiability']['relief89'] = 25000
    m['taxLiability']['form10EFiled'] = True
    m['taxLiability']['form10EAckNo'] = '100000000000009'
    return m


def _interest_24b_exhausted():
    """24(b) interest fully exhausted, so 80EE / 80EEA is permissible -- A-221."""
    m = house_property_base()
    p = m['income']['properties'][0]
    p['interestOnBorrowedCapital'] = 250000
    p['schedule24B'][0]['interestPaid'] = 250000
    m['deductions']['s80EE'] = 50000
    m['deductions']['schedule80EE'] = [
        {
            'id': 'ee1',
            'loanTakenFrom': 'B',
            'lenderName': 'HDFC BANK',
            'loanAccountNo': 'HL123456',
            'dateOfLoan': '2016-09-01',
            'totalLoanAmount': 3000000,
            'loanOutstandingAmount': 2000000,
            'interest': 50000,
        }
    ]
    return m


# ---------------------------------------------------------------------------
# NamedBase[] -- {'name': str, 'build': callable} to mirror the TS shape.
# ---------------------------------------------------------------------------

COVERAGE_BASES = [
    {'name': 'newRegime', 'build': new_regime_base},
    {'name': 'oldRegime', 'build': old_regime_base},
    {'name': 'senior', 'build': senior_old_regime_base},
    {'name': 'houseProperty', 'build': house_property_base},
    {'name': 'allSchedules', 'build': _with_all_schedules},
    {'name': 'with80EEA', 'build': _with_80eea},
    {'name': 'with80GG', 'build': _with_80gg},
    {'name': 'with80CCH', 'build': _with_80cch},
    {'name': 'newRegimeWithSchedules', 'build': _new_regime_with_schedules},
    {'name': 'allTaxPaid', 'build': _with_all_tax_paid},
    {'name': 'revisedLate', 'build': _revised_late},
    {'name': 'representativeAndNotice', 'build': _representative_and_notice},
    {'name': 'pensionerOldRegime', 'build': _pensioner_old_regime},
    {'name': 'otherEmployerOldRegime', 'build': _other_employer_old_regime},
    {'name': 'all80GBlocks', 'build': _all_80g_blocks},
    {'name': 'schedule80DOtherBlocks', 'build': _schedule_80d_other_blocks},
    {'name': 'schedule80DNotClaiming', 'build': _schedule_80d_not_claiming},
    {'name': 'severeDisability', 'build': _severe_disability},
    {'name': 'original142', 'build': _original_142},
    {'name': 'proceedings148', 'build': _proceedings_148},
    {'name': 'newRegimeHpLoss', 'build': _new_regime_hp_loss},
    {'name': 'with10_10CC', 'build': _with_10_10cc},
    {'name': 'withJudgeExemptIncome', 'build': _with_judge_exempt_income},
    {'name': 'revisedAfterBelated', 'build': _revised_after_belated},
    {'name': 'highIncomeNewRegime', 'build': _high_income_new_regime},
    {'name': 'revisedLateHighIncome', 'build': _revised_late_high_income},
    {'name': 'miscellaneousFlags', 'build': _miscellaneous_flags},
    {'name': 'interest24bExhausted', 'build': _interest_24b_exhausted},
    {'name': 'empty', 'build': empty_base},
]

assert len(COVERAGE_BASES) == 29
