"""Blank ReturnModel factory. Ported from
itr1-module/packages/core/src/model/blank.ts.

Python has no static type system to carry the TS interfaces, so the model is
represented as a plain (JSON-serializable) dict tree with identical field
names/nesting to the TS `ReturnModel`. This dict is what gets stored verbatim
in the `TaxReturn.data` JSONField (see itr/models.py) and is what
`itr/engine/facts.py` / `itr/engine/compute.py` read and write.
"""

ALL_SCREENS = [
    'PERSONAL_INFO',
    'GROSS_TOTAL_INCOME',
    'TOTAL_DEDUCTIONS',
    'TAX_PAID',
    'TAX_LIABILITY',
    'TAX_SUMMARY',
    'VALIDATION',
]


def blank_address():
    return {
        'flatDoorBuilding': '',
        'premiseBuildingName': '',
        'roadStreet': '',
        'areaLocality': '',
        'townCityDistrict': '',
        'stateCode': '',
        'countryCode': '91',
        'pinCode': '',
        'zipCode': '',
    }


def blank_quarterly():
    return {
        'Upto15Of6': 0,
        'Upto15Of9': 0,
        'Up16Of9To15Of12': 0,
        'Up16Of12To15Of3': 0,
        'Up16Of3To31Of3': 0,
    }


def blank_hra():
    return {
        'placeOfWork': '',
        'actualHraReceived': 0,
        'actualRentPaid': 0,
        'salary17_1': 0,
        'basicSalary': 0,
        'dearnessAllowance': 0,
    }


def _blank_80d_block():
    return {
        'healthInsurancePremium': 0,
        'insurers': [],
        'preventiveHealthCheckup': 0,
        'medicalExpenditure': 0,
    }


def blank_80d():
    return {
        'selfFamilySeniorFlag': '',
        'selfFamily': _blank_80d_block(),
        'selfFamilySenior': _blank_80d_block(),
        'parentsSeniorFlag': '',
        'parents': _blank_80d_block(),
        'parentsSenior': _blank_80d_block(),
    }


def blank_80ddu():
    return {
        'natureOfDisability': '',
        'typeOfDisability': '',
        'amount': 0,
        'dependentType': '',
        'dependentPan': '',
        'dependentAadhaar': '',
        'form10IAFiled': False,
        'form10IAAckNo': '',
        'udidNo': '',
    }


def _blank_screen_status():
    return {s: 'NOT_STARTED' for s in ALL_SCREENS}


def blank_return_model(tenant_id, return_id):
    return {
        'modelVersion': 1,
        'ay': '2026-27',
        'tenantId': tenant_id,
        'returnId': return_id,

        'personalInfo': {
            'firstName': '',
            'middleName': '',
            'lastName': '',
            'pan': '',
            'dob': '',
            'aadhaar': '',
            'aadhaarLinkedToPan': None,
            'aadhaarMatchesProfile': None,
            'status': 'INDIVIDUAL',
            'dateOfFormation': '',
            'contact': {
                'primaryMobileCountryCode': '91',
                'primaryMobile': '',
                'secondaryMobileCountryCode': '',
                'secondaryMobile': '',
                'primaryEmail': '',
                'secondaryEmail': '',
            },
            'primaryAddress': blank_address(),
            'secondaryAddressSameAsPrimary': 'Y',
            'secondaryAddress': blank_address(),
            'employerCategory': '',
            'armedForcesJoiningDate': '',
        },

        'filingStatus': {
            'returnFileSec': 11,
            'filedInResponseToNotice': False,
            'noticeSection': None,
            'noticeNo': '',
            'noticeDate': '',
            'origReturnAckNo': '',
            'origReturnFiledDate': '',
            'origReturnFileSec': None,
            'proceedingsInitiatedUs148': False,
            'a23ResponsesOriginal': '',
            'a23ResponsesCurrent': '',
            'filingDate': '',
            'optOutOfNewRegime': 'N',
            'seventhProviso139': 'N',
            'seventhProviso': {
                'travelExpenseAbove2Lakh': 'N',
                'travelExpenseAmount': None,
                'electricityAbove1Lakh': 'N',
                'electricityAmount': None,
                'clauseIvApplies': 'N',
                'clauseIvDetails': [],
            },
            'representativeAssesseeFlag': 'N',
            'representativeAssessee': None,
        },

        'income': {
            'employers': [],
            'salary17_1': 0,
            'perquisites17_2': 0,
            'profitsInLieu17_3': 0,
            'exemptAllowances': [],
            'hra10_13A': blank_hra(),
            'entertainmentAllowance16ii': 0,
            'professionalTax16iii': 0,
            'properties': [],
            'otherSources': [],
            'exemptIncome': [],
            'ltcg112A': {'totalSaleConsideration': 0, 'totalCostOfAcquisition': 0},
        },

        'deductions': {
            's80C': 0,
            'schedule80C': [],
            's80CCC': 0,
            'pensionContribution80CCC': [],
            's80CCD1': 0,
            's80CCD1B': 0,
            'pranNumbers': [],
            's80CCD2': 0,
            's80CCH': 0,
            's80D': 0,
            'schedule80D': blank_80d(),
            's80DD': 0,
            'schedule80DD': blank_80ddu(),
            's80DDB': 0,
            's80DDBUsrType': '',
            's80DDBDisease': '',
            's80E': 0,
            'schedule80E': [],
            's80EE': 0,
            'schedule80EE': [],
            's80EEA': 0,
            'schedule80EEA': [],
            'stampDutyValue80EEA': 0,
            's80EEB': 0,
            'schedule80EEB': [],
            's80G': 0,
            'schedule80G': {
                'don100Percent': [],
                'don50PercentNoApprReqd': [],
                'don100PercentApprReqd': [],
                'don50PercentApprReqd': [],
            },
            's80GG': 0,
            'form10BAFiled': False,
            'form10BAAckNo': '',
            's80GGA': 0,
            'schedule80GGA': [],
            's80GGC': 0,
            'schedule80GGC': [],
            's80TTA': 0,
            's80TTB': 0,
            's80U': 0,
            'schedule80U': blank_80ddu(),
        },

        'taxPaid': {'tds1': [], 'tds2': [], 'tds3': [], 'tcs': [], 'challans': []},

        'taxLiability': {
            'relief89': 0,
            'form10EFiled': False,
            'form10EAckNo': '',
            'interest234AOverride': None,
            'interest234BOverride': None,
            'fee234FOverride': None,
        },

        'bankAccounts': [],

        'verification': {
            'assesseeVerName': '',
            'fatherName': '',
            'assesseeVerPan': '',
            'capacity': 'S',
            'place': '',
            'date': '',
        },

        'taxReturnPreparer': {
            'enabled': False,
            'identificationNo': '',
            'name': '',
            'reimbursementFromGovt': 0,
        },

        'screenStatus': _blank_screen_status(),
        'advisoryAcknowledgements': {},
    }
