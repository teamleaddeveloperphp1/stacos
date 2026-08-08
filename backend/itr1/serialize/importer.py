"""Round-trip import.

Ported from itr1-module/packages/core/src/serialize/importer.ts.

NON-NEGOTIABLE 11.5: accept a previously generated JSON, map it back into the
model, RECOMPUTE every derived field, and re-run validation. Where a
recomputed value differs from the imported value the difference is reported
as a discrepancy -- never silently overwritten. That is how a preparer
catches a corrupted draft.
"""

from dataclasses import dataclass, field

from itr1.engine.compute import compute as compute_return
from itr1.model_blank import blank_80d, blank_80ddu, blank_address, blank_hra, blank_return_model
from itr1.util.num import n

_seq = 0


def _id(prefix):
    global _seq
    _seq += 1
    return f'{prefix}-{_seq}'


def _obj(v):
    return v if isinstance(v, dict) else {}


def _arr(v):
    return v if isinstance(v, list) else []


def _s(v):
    return '' if v is None else str(v)


def _read_address(a):
    return {
        'flatDoorBuilding': _s(a.get('ResidenceNo')),
        'premiseBuildingName': _s(a.get('ResidenceName')),
        'roadStreet': _s(a.get('RoadOrStreet')),
        'areaLocality': _s(a.get('LocalityOrArea')),
        'townCityDistrict': _s(a.get('CityOrTownOrDistrict')),
        'stateCode': _s(a.get('StateCode')),
        'countryCode': _s(a.get('CountryCode')) or '91',
        'pinCode': _s(a.get('PinCode')),
        'zipCode': _s(a.get('ZipCode')),
    }


def _read_loan_rows(rows, interest_key):
    return [
        {
            'id': _id('loan'),
            'loanTakenFrom': _s(r.get('LoanTknFrom')) or '',
            'lenderName': _s(r.get('BankOrInstnName')),
            'loanAccountNo': _s(r.get('LoanAccNoOfBankOrInstnRefNo')),
            'dateOfLoan': _s(r.get('DateofLoan')),
            'totalLoanAmount': n(r.get('TotalLoanAmt')),
            'loanOutstandingAmount': n(r.get('LoanOutstndngAmt')),
            'interest': n(r.get(interest_key)),
            'vehicleRegNo': _s(r.get('VehicleRegNo')) or None,
        }
        for r in rows
    ]


def _read_80d_block(premium, details, preventive, medical):
    return {
        'healthInsurancePremium': n(premium),
        'insurers': [
            {
                'id': _id('ins'),
                'insurerName': _s(i.get('InsurerName')),
                'policyNo': _s(i.get('PolicyNo')),
                'amount': n(i.get('HealthInsAmt')),
            }
            for i in _arr(_obj(details).get('Sch80DInsDtls'))
        ],
        'preventiveHealthCheckup': n(preventive),
        'medicalExpenditure': n(medical),
    }


def _read_donees(block):
    out = []
    for r in _arr(_obj(block).get('DoneeWithPan')):
        ad = _obj(r.get('AddressDetail'))
        out.append(
            {
                'id': _id('donee'),
                'name': _s(r.get('DoneeWithPanName')),
                'pan': _s(r.get('DoneePAN')),
                'arnNo': _s(r.get('ArnNbr')),
                'address': {
                    'flatDoorBuilding': _s(ad.get('AddrDetail')),
                    'townCityDistrict': _s(ad.get('CityOrTownOrDistrict')),
                    'stateCode': _s(ad.get('StateCode')),
                    'pinCode': _s(ad.get('PinCode')),
                },
                'donationCash': n(r.get('DonationAmtCash')),
                'donationOtherMode': n(r.get('DonationAmtOtherMode')),
                'transactionRefNo': _s(r.get('TransactionRefNum')),
                'ifsc': _s(r.get('IFSCCode')),
            }
        )
    return out


_KNOWN_ITR1_ELEMENTS = {
    'CreationInfo', 'Form_ITR1', 'PersonalInfo', 'FilingStatus', 'ITR1_IncomeDeductions',
    'ITR1_TaxComputation', 'TaxPaid', 'Refund', 'Schedule80G', 'Schedule80GGA', 'Schedule80GGC',
    'Schedule80D', 'Schedule80DD', 'Schedule80U', 'Schedule80E', 'Schedule80EE', 'Schedule80EEA',
    'Schedule80EEB', 'Schedule80C', 'ScheduleEA10_13A', 'TDSonSalaries', 'TDSonOthThanSals',
    'ScheduleTDS3Dtls', 'ScheduleTCS', 'TaxPayments', 'LTCG112A', 'Verification', 'TaxReturnPreparer',
}


@dataclass
class Discrepancy:
    path: str
    label: str
    imported: object
    recomputed: object


@dataclass
class ImportResult:
    model: dict
    discrepancies: list = field(default_factory=list)
    # Elements present in the file that this build does not map.
    unmappedElements: list = field(default_factory=list)


def import_from_json(document, ctx):
    """`ctx`: dict with `tenantId`, `returnId`, optional `filingDate`."""
    p = _obj(_obj(document.get('ITR')).get('ITR1'))
    m = blank_return_model(ctx['tenantId'], ctx['returnId'])

    unmapped_elements = [k for k in p.keys() if k not in _KNOWN_ITR1_ELEMENTS]

    # ---- Personal info -----------------------------------------------------
    pi = _obj(p.get('PersonalInfo'))
    name_node = _obj(pi.get('AssesseeName'))
    addr = _obj(pi.get('Address'))
    m['personalInfo']['firstName'] = _s(name_node.get('FirstName'))
    m['personalInfo']['middleName'] = _s(name_node.get('MiddleName'))
    m['personalInfo']['lastName'] = _s(name_node.get('SurNameOrOrgName'))
    m['personalInfo']['pan'] = _s(pi.get('PAN'))
    m['personalInfo']['dob'] = _s(pi.get('DOB'))
    m['personalInfo']['aadhaar'] = _s(pi.get('AadhaarCardNo'))
    m['personalInfo']['employerCategory'] = _s(pi.get('EmployerCategory')) or ''
    m['personalInfo']['primaryAddress'] = _read_address(addr)
    m['personalInfo']['contact'] = {
        'primaryMobileCountryCode': _s(addr.get('CountryCodeMobile')) or '91',
        'primaryMobile': _s(addr.get('MobileNo')),
        'secondaryMobileCountryCode': _s(addr.get('CountryCodeMobileNoSec')),
        'secondaryMobile': _s(addr.get('MobileNoSec')),
        'primaryEmail': _s(addr.get('EmailAddress')),
        'secondaryEmail': _s(addr.get('EmailAddressSec')),
    }
    m['personalInfo']['secondaryAddressSameAsPrimary'] = _s(pi.get('SecondaryAdd')) or 'Y'
    m['personalInfo']['secondaryAddress'] = (
        _read_address(_obj(pi.get('AlternateAddress'))) if pi.get('AlternateAddress') else blank_address()
    )

    # ---- Filing status ------------------------------------------------------
    fs = _obj(p.get('FilingStatus'))
    m['filingStatus']['returnFileSec'] = int(fs.get('ReturnFileSec')) if fs.get('ReturnFileSec') else 11
    m['filingStatus']['optOutOfNewRegime'] = _s(fs.get('OptOutNewTaxRegime')) or 'N'
    m['filingStatus']['seventhProviso139'] = _s(fs.get('SeventhProvisio139')) or 'N'
    m['filingStatus']['origReturnAckNo'] = _s(fs.get('ReceiptNo'))
    m['filingStatus']['origReturnFiledDate'] = _s(fs.get('OrigRetFiledDate'))
    m['filingStatus']['noticeNo'] = _s(fs.get('NoticeNo'))
    m['filingStatus']['noticeDate'] = _s(fs.get('NoticeDateUnderSec'))
    m['filingStatus']['representativeAssesseeFlag'] = _s(fs.get('AsseseeRepFlg')) or 'N'
    if fs.get('AssesseeRep'):
        rep = _obj(fs.get('AssesseeRep'))
        m['filingStatus']['representativeAssessee'] = {
            'name': _s(rep.get('RepName')),
            'pan': '',
            'email': _s(rep.get('RepEmailID')),
            'mobileCountryCode': _s(rep.get('CountryCodeRepMobileNo')),
            'mobile': _s(rep.get('RepMobileNo')),
            'capacity': '',
            'address': {},
        }
    m['filingStatus']['seventhProviso']['travelExpenseAbove2Lakh'] = (
        _s(fs.get('IncrExpAggAmt2LkTrvFrgnCntryFlg')) or 'N'
    )
    m['filingStatus']['seventhProviso']['travelExpenseAmount'] = (
        n(fs.get('AmtSeventhProvisio139ii')) if fs.get('AmtSeventhProvisio139ii') else None
    )
    m['filingStatus']['seventhProviso']['electricityAbove1Lakh'] = (
        _s(fs.get('IncrExpAggAmt1LkElctrctyPrYrFlg')) or 'N'
    )
    m['filingStatus']['seventhProviso']['electricityAmount'] = (
        n(fs.get('AmtSeventhProvisio139iii')) if fs.get('AmtSeventhProvisio139iii') else None
    )
    m['filingStatus']['seventhProviso']['clauseIvApplies'] = _s(fs.get('clauseiv7provisio139i')) or 'N'
    m['filingStatus']['seventhProviso']['clauseIvDetails'] = [
        {'nature': _s(r.get('clauseiv7provisio139iNature')), 'amount': n(r.get('clauseiv7provisio139iAmount'))}
        for r in _arr(fs.get('clauseiv7provisio139iDtls'))
    ]
    # The filing date is not carried in the CBDT schema; the caller supplies it.
    m['filingStatus']['filingDate'] = ctx.get('filingDate') or ''

    # ---- Income --------------------------------------------------------------
    inc = _obj(p.get('ITR1_IncomeDeductions'))
    m['income']['salary17_1'] = n(inc.get('Salary'))
    m['income']['perquisites17_2'] = n(inc.get('PerquisitesValue'))
    m['income']['profitsInLieu17_3'] = n(inc.get('ProfitsInSalary'))
    m['income']['entertainmentAllowance16ii'] = n(inc.get('EntertainmentAlw16ii'))
    m['income']['professionalTax16iii'] = n(inc.get('ProfessionalTaxUs16iii'))
    m['income']['exemptAllowances'] = [
        {'id': _id('allw'), 'nature': _s(r.get('SalNatureDesc')), 'amount': n(r.get('SalOthAmount'))}
        for r in _arr(_obj(inc.get('AllwncExemptUs10')).get('AllwncExemptUs10Dtls'))
    ]

    def _read_other_source(r):
        dr = _obj(_obj(r.get('DividendInc')).get('DateRange'))
        return {
            'id': _id('oth'),
            'nature': _s(r.get('OthSrcNatureDesc')),
            'otherNatureDescription': _s(r.get('OthSrcOthNatOfInc')),
            'amount': n(r.get('OthSrcOthAmount')),
            'dividendQuarterly': (
                {
                    'Upto15Of6': n(dr.get('Upto15Of6')),
                    'Upto15Of9': n(dr.get('Upto15Of9')),
                    'Up16Of9To15Of12': n(dr.get('Up16Of9To15Of12')),
                    'Up16Of12To15Of3': n(dr.get('Up16Of12To15Of3')),
                    'Up16Of3To31Of3': n(dr.get('Up16Of3To31Of3')),
                }
                if r.get('DividendInc')
                else None
            ),
        }

    m['income']['otherSources'] = [
        _read_other_source(r) for r in _arr(_obj(inc.get('OthersInc')).get('OthersIncDtlsOthSrc'))
    ]
    m['income']['exemptIncome'] = [
        {
            'id': _id('ex'),
            'category': _s(r.get('Category')),
            'subCategory': _s(r.get('SubCategory')),
            'description': _s(r.get('Description')),
            'amount': n(r.get('OthAmount')),
        }
        for r in _arr(_obj(inc.get('ExemptIncAgriOthUs10')).get('ExemptIncAgriOthUs10Dtls'))
    ]

    def _read_property(p_):
        rent = _obj(p_.get('Rentdetails'))
        s24 = _obj(rent.get('Section24B'))
        ad = _obj(p_.get('AddressDetailWithZipCode'))
        return {
            'id': _id('hp'),
            'address': {
                'flatDoorBuilding': _s(ad.get('AddrDetail')),
                'townCityDistrict': _s(ad.get('CityOrTownOrDistrict')),
                'stateCode': _s(ad.get('StateCode')),
                'countryCode': _s(ad.get('CountryCode')),
                'pinCode': _s(ad.get('PinCode')),
                'zipCode': _s(ad.get('ZipCode')),
            },
            'propertyOwner': _s(p_.get('PropertyOwner')),
            'propertyOwnerOther': _s(p_.get('PropertyOwnerOther')),
            'coOwned': _s(p_.get('PropCoOwnedFlg')) or '',
            'assesseeSharePercent': n(p_.get('AsseseeShareProperty')),
            'coOwners': [
                {
                    'id': _id('co'),
                    'name': _s(co.get('NameCoOwner')),
                    'pan': _s(co.get('PAN_CoOwner')),
                    'aadhaar': _s(co.get('Aadhaar_CoOwner')),
                    'sharePercent': n(co.get('PercentShareProperty')),
                }
                for co in _arr(p_.get('CoOwners'))
            ],
            'propertyType': _s(p_.get('ifLetOut')),
            'tenants': [
                {
                    'id': _id('ten'),
                    'name': _s(t.get('NameofTenant')),
                    'pan': _s(t.get('PANofTenant')),
                    'aadhaar': _s(t.get('AadhaarofTenant')),
                    'panOrTan': _s(t.get('PANTANofTenant')),
                }
                for t in _arr(p_.get('TenantDetails'))
            ],
            'grossRent': n(rent.get('AnnualLetableValue')),
            'rentNotRealized': n(rent.get('RentNotRealized')),
            'localTaxes': n(rent.get('LocalTaxes')),
            'interestOnBorrowedCapital': n(rent.get('IntOnBorwCap')),
            'schedule24B': [
                {
                    'id': _id('l24b'),
                    'loanTakenFrom': _s(r.get('LoanTknFrom')),
                    'lenderName': _s(r.get('BankOrInstnName')),
                    'loanAccountNo': _s(r.get('LoanAccNoOfBankOrInstnRefNo')),
                    'dateOfLoan': _s(r.get('DateofLoan')),
                    'totalLoanAmount': n(r.get('TotalLoanAmt')),
                    'loanOutstandingAmount': n(r.get('LoanOutstndngAmt')),
                    'interestPaid': n(r.get('InterestUs24B')),
                }
                for r in _arr(s24.get('Section24BDtls'))
            ],
            'arrearsUnrealisedRentReceived': n(rent.get('ArrearsUnrealizedRentRcvd')),
        }

    m['income']['properties'] = [_read_property(pp) for pp in _arr(inc.get('PropertyDetails'))]

    ltcg = _obj(p.get('LTCG112A'))
    m['income']['ltcg112A'] = {
        'totalSaleConsideration': n(ltcg.get('TotSaleCnsdrn')),
        'totalCostOfAcquisition': n(ltcg.get('TotCstAcqisn')),
    }

    ea = _obj(p.get('ScheduleEA10_13A'))
    m['income']['hra10_13A'] = (
        {
            'placeOfWork': _s(ea.get('Placeofwork')) or '',
            'actualHraReceived': n(ea.get('ActlHRARecv')),
            'actualRentPaid': n(ea.get('ActlRentPaid')),
            'salary17_1': n(ea.get('DtlsSalUsSec171')),
            'basicSalary': n(ea.get('BasicSalary')),
            'dearnessAllowance': n(ea.get('DearnessAllwnc')),
        }
        if p.get('ScheduleEA10_13A')
        else blank_hra()
    )

    # ---- Deductions -----------------------------------------------------------
    usr = _obj(inc.get('UsrDeductUndChapVIA'))
    d = m['deductions']
    d['s80C'] = n(usr.get('Section80C'))
    d['s80CCC'] = n(usr.get('Section80CCC'))
    d['s80CCD1'] = n(usr.get('Section80CCDEmployeeOrSE'))
    d['s80CCD1B'] = n(usr.get('Section80CCD1B'))
    d['s80CCD2'] = n(usr.get('Section80CCDEmployer'))
    d['s80CCH'] = n(usr.get('AnyOthSec80CCH'))
    d['s80D'] = n(usr.get('Section80D'))
    d['s80DD'] = n(usr.get('Section80DD'))
    d['s80DDB'] = n(usr.get('Section80DDB'))
    d['s80DDBUsrType'] = _s(usr.get('Section80DDBUsrType')) or ''
    d['s80DDBDisease'] = _s(usr.get('NameOfSpecDisease80DDB'))
    d['s80E'] = n(usr.get('Section80E'))
    d['s80EE'] = n(usr.get('Section80EE'))
    d['s80EEA'] = n(usr.get('Section80EEA'))
    d['s80EEB'] = n(usr.get('Section80EEB'))
    d['s80G'] = n(usr.get('Section80G'))
    d['s80GG'] = n(usr.get('Section80GG'))
    d['form10BAAckNo'] = _s(usr.get('Form10BAAckNum'))
    d['form10BAFiled'] = bool(d['form10BAAckNo'])
    d['s80GGA'] = n(usr.get('Section80GGA'))
    d['s80GGC'] = n(usr.get('Section80GGC'))
    d['s80TTA'] = n(usr.get('Section80TTA'))
    d['s80TTB'] = n(usr.get('Section80TTB'))
    d['s80U'] = n(usr.get('Section80U'))
    d['pranNumbers'] = [_s(r.get('PRANNum')) for r in _arr(usr.get('PRANDtls')) if _s(r.get('PRANNum'))]
    d['pensionContribution80CCC'] = [
        {
            'id': _id('pc'),
            'typeOfIdentifier': _s(r.get('TypeofIdentifier')),
            'nameOfIdentifier': _s(r.get('NameofIdentifier')),
            'amount': n(r.get('Amount')),
        }
        for r in _arr(usr.get('PensionContribution80CCC'))
    ]

    d['schedule80C'] = [
        {
            'id': _id('80c'),
            'typeOfIdentifier': '',
            'identificationNo': _s(r.get('IdentificationNo')),
            'amount': n(r.get('Amount')),
        }
        for r in _arr(_obj(p.get('Schedule80C')).get('Schedule80CDtls'))
    ]
    d['schedule80E'] = _read_loan_rows(_arr(_obj(p.get('Schedule80E')).get('Schedule80EDtls')), 'Interest80E')
    d['schedule80EE'] = _read_loan_rows(_arr(_obj(p.get('Schedule80EE')).get('Schedule80EEDtls')), 'Interest80EE')
    d['schedule80EEA'] = _read_loan_rows(
        _arr(_obj(p.get('Schedule80EEA')).get('Schedule80EEADtls')), 'Interest80EEA'
    )
    d['stampDutyValue80EEA'] = n(_obj(p.get('Schedule80EEA')).get('PropStmpDtyVal'))
    d['schedule80EEB'] = _read_loan_rows(
        _arr(_obj(p.get('Schedule80EEB')).get('Schedule80EEBDtls')), 'Interest80EEB'
    )

    if p.get('Schedule80D'):
        h = _obj(_obj(p.get('Schedule80D')).get('Sec80DSelfFamSrCtznHealth'))
        d['schedule80D'] = {
            'selfFamilySeniorFlag': _s(h.get('SeniorCitizenFlag')) or '',
            'selfFamily': _read_80d_block(
                h.get('HealthInsPremSlfFam'), h.get('Sec80DSelfFamHIDtls'), h.get('PrevHlthChckUpSlfFam'), 0
            ),
            'selfFamilySenior': _read_80d_block(
                h.get('HlthInsPremSlfFamSrCtzn'),
                h.get('Sec80DSelfFamSrCtznHIDtls'),
                h.get('PrevHlthChckUpSlfFamSrCtzn'),
                h.get('MedicalExpSlfFamSrCtzn'),
            ),
            'parentsSeniorFlag': _s(h.get('ParentsSeniorCitizenFlag')) or '',
            'parents': _read_80d_block(
                h.get('HlthInsPremParents'), h.get('Sec80DParentsHIDtls'), h.get('PrevHlthChckUpParents'), 0
            ),
            'parentsSenior': _read_80d_block(
                h.get('HlthInsPremParentsSrCtzn'),
                h.get('Sec80DParentsSrCtznHIDtls'),
                h.get('PrevHlthChckUpParentsSrCtzn'),
                h.get('MedicalExpParentsSrCtzn'),
            ),
        }
    else:
        d['schedule80D'] = blank_80d()

    dd = _obj(p.get('Schedule80DD'))
    d['schedule80DD'] = (
        {
            'natureOfDisability': _s(dd.get('NatureOfDisability')),
            'typeOfDisability': _s(dd.get('TypeOfDisability')),
            'amount': n(dd.get('DeductionAmount')),
            'dependentType': _s(dd.get('DependentType')),
            'dependentPan': _s(dd.get('DependentPan')),
            'dependentAadhaar': _s(dd.get('DependentAadhaar')),
            'form10IAFiled': bool(_s(dd.get('Form10IAAckNum'))),
            'form10IAAckNo': _s(dd.get('Form10IAAckNum')),
            'udidNo': _s(dd.get('UDIDNum')),
        }
        if p.get('Schedule80DD')
        else blank_80ddu()
    )

    u = _obj(p.get('Schedule80U'))
    d['schedule80U'] = (
        {
            'natureOfDisability': _s(u.get('NatureOfDisability')),
            'typeOfDisability': _s(u.get('TypeOfDisability')),
            'amount': n(u.get('DeductionAmount')),
            'form10IAFiled': bool(_s(u.get('Form10IAAckNum'))),
            'form10IAAckNo': _s(u.get('Form10IAAckNum')),
            'udidNo': _s(u.get('UDIDNum')),
        }
        if p.get('Schedule80U')
        else blank_80ddu()
    )

    g80 = _obj(p.get('Schedule80G'))
    d['schedule80G'] = {
        'don100Percent': _read_donees(g80.get('Don100Percent')),
        'don50PercentNoApprReqd': _read_donees(g80.get('Don50PercentNoApprReqd')),
        'don100PercentApprReqd': _read_donees(g80.get('Don100PercentApprReqd')),
        'don50PercentApprReqd': _read_donees(g80.get('Don50PercentApprReqd')),
    }
    d['schedule80GGA'] = []
    for r in _arr(_obj(p.get('Schedule80GGA')).get('DonationDtlsSciRsrchRuralDev')):
        ad = _obj(r.get('AddressDetail'))
        d['schedule80GGA'].append(
            {
                'id': _id('gga'),
                'relevantClause': _s(r.get('RelevantClauseUndrDedClaimed')),
                'name': _s(r.get('NameOfDonee')),
                'pan': _s(r.get('DoneePAN')),
                'address': {
                    'flatDoorBuilding': _s(ad.get('AddrDetail')),
                    'townCityDistrict': _s(ad.get('CityOrTownOrDistrict')),
                    'stateCode': _s(ad.get('StateCode')),
                    'pinCode': _s(ad.get('PinCode')),
                },
                'donationCash': n(r.get('DonationAmtCash')),
                'donationOtherMode': n(r.get('DonationAmtOtherMode')),
            }
        )
    d['schedule80GGC'] = [
        {
            'id': _id('ggc'),
            'donationDate': _s(r.get('DonationDate')),
            'politicalPartyName': _s(r.get('PoliticalPartyName')),
            'politicalPartyPan': _s(r.get('PoliticalPartyPAN')),
            'donationCash': n(r.get('DonationAmtCash')),
            'donationOtherMode': n(r.get('DonationAmtOtherMode')),
            'transactionRefNo': _s(r.get('TransactionRefNum')),
            'ifsc': _s(r.get('IFSCCode')),
        }
        for r in _arr(_obj(p.get('Schedule80GGC')).get('Schedule80GGCDetails'))
    ]

    # ---- Tax paid ---------------------------------------------------------
    m['taxPaid']['tds1'] = []
    for r in _arr(_obj(p.get('TDSonSalaries')).get('TDSonSalary')):
        e = _obj(r.get('EmployerOrDeductorOrCollectDetl'))
        m['taxPaid']['tds1'].append(
            {
                'id': _id('tds1'),
                'tan': _s(e.get('TAN')),
                'deductorName': _s(e.get('EmployerOrDeductorOrCollecterName')),
                'incomeChargeableSalary': n(r.get('IncChrgSal')),
                'totalTaxDeducted': n(r.get('TotalTDSSal')),
            }
        )
    m['taxPaid']['tds2'] = []
    for r in _arr(_obj(p.get('TDSonOthThanSals')).get('TDSonOthThanSal')):
        e = _obj(r.get('EmployerOrDeductorOrCollectDetl'))
        m['taxPaid']['tds2'].append(
            {
                'id': _id('tds2'),
                'tanOrPan': _s(e.get('TAN')),
                'deductorName': _s(e.get('EmployerOrDeductorOrCollecterName')),
                'grossReceipt': n(r.get('AmtForTaxDeduct')),
                'deductedYear': _s(r.get('DeductedYr')),
                'taxDeducted': n(r.get('TotTDSOnAmtPaid')),
                'tdsClaimedThisYear': n(r.get('ClaimOutOfTotTDSOnAmtPaid')),
                'tdsSection': _s(r.get('TDSSection')),
                'headOfIncome': '',
            }
        )
    m['taxPaid']['tds3'] = [
        {
            'id': _id('tds3'),
            'panOfTenant': _s(r.get('PANofTenant')),
            'aadhaarOfTenant': _s(r.get('AadhaarofTenant')),
            'nameOfTenant': _s(r.get('NameOfTenant')),
            'grossReceipt': n(r.get('GrsRcptToTaxDeduct')),
            'deductedYear': _s(r.get('DeductedYr')),
            'taxDeducted': n(r.get('TDSDeducted')),
            'tdsClaimedThisYear': n(r.get('TDSClaimed')),
            'tdsSection': _s(r.get('TDSSection')),
            'headOfIncome': '',
        }
        for r in _arr(_obj(p.get('ScheduleTDS3Dtls')).get('TDS3Details'))
    ]
    m['taxPaid']['tcs'] = []
    for r in _arr(_obj(p.get('ScheduleTCS')).get('TCS')):
        e = _obj(r.get('EmployerOrDeductorOrCollectDetl'))
        m['taxPaid']['tcs'].append(
            {
                'id': _id('tcs'),
                'tan': _s(e.get('TAN')),
                'collectorName': _s(e.get('EmployerOrDeductorOrCollecterName')),
                'taxCollected': n(r.get('AmtTaxCollected')),
                'collectedYear': _s(r.get('CollectedYr')),
                'totalTcs': n(r.get('TotalTCS')),
                'tcsClaimedThisYear': n(r.get('AmtTCSClaimedThisYear')),
            }
        )
    m['taxPaid']['challans'] = [
        {
            'id': _id('chl'),
            'bsrCode': _s(r.get('BSRCode')),
            'dateOfDeposit': _s(r.get('DateDep')),
            'challanSerialNo': _s(r.get('SrlNoOfChaln')),
            'amount': n(r.get('Amt')),
        }
        for r in _arr(_obj(p.get('TaxPayments')).get('TaxPayment'))
    ]

    # ---- Tax liability inputs ------------------------------------------------
    tc = _obj(p.get('ITR1_TaxComputation'))
    ip = _obj(tc.get('IntrstPay'))
    m['taxLiability']['relief89'] = n(tc.get('Section89'))
    m['taxLiability']['interest234AOverride'] = (
        None if ip.get('IntrstPayUs234A') is None else n(ip.get('IntrstPayUs234A'))
    )
    m['taxLiability']['interest234BOverride'] = (
        None if ip.get('IntrstPayUs234B') is None else n(ip.get('IntrstPayUs234B'))
    )
    m['taxLiability']['fee234FOverride'] = (
        None if ip.get('LateFilingFee234F') is None else n(ip.get('LateFilingFee234F'))
    )

    # ---- Bank / verification ------------------------------------------------
    m['bankAccounts'] = [
        {
            'id': _id('bank'),
            'ifsc': _s(b.get('IFSCCode')),
            'bankName': _s(b.get('BankName')),
            'accountNumber': _s(b.get('BankAccountNo')),
            'accountType': _s(b.get('AccountType')),
            'nominateForRefund': _s(b.get('UseForRefund')) == 'true',
            'ifscVerified': None,
            'ifscVerificationNote': 'Re-verification required after import',
        }
        for b in _arr(_obj(_obj(p.get('Refund')).get('BankAccountDtls')).get('AddtnlBankDetails'))
    ]

    ver = _obj(p.get('Verification'))
    decl = _obj(ver.get('Declaration'))
    m['verification'] = {
        'assesseeVerName': _s(decl.get('AssesseeVerName')),
        'fatherName': _s(decl.get('FatherName')),
        'assesseeVerPan': _s(decl.get('AssesseeVerPAN')),
        'capacity': _s(ver.get('Capacity')) or 'S',
        'place': _s(ver.get('Place')),
        'date': '',
    }

    if p.get('TaxReturnPreparer'):
        trp = _obj(p.get('TaxReturnPreparer'))
        m['taxReturnPreparer'] = {
            'enabled': True,
            'identificationNo': _s(trp.get('IdentificationNoOfTRP')),
            'name': _s(trp.get('NameOfTRP')),
            'reimbursementFromGovt': n(trp.get('ReImbFrmGov')),
        }

    # ---- Recompute and diff --------------------------------------------------
    c = compute_return(m)
    discrepancies = []

    def check(path, label, imported_raw, recomputed):
        if imported_raw is None:
            return
        imported = n(imported_raw)
        if imported != recomputed:
            discrepancies.append(Discrepancy(path=path, label=label, imported=imported, recomputed=recomputed))

    check('ITR1_IncomeDeductions.GrossSalary', 'Gross salary', inc.get('GrossSalary'), c['salary']['grossSalary'])
    check('ITR1_IncomeDeductions.NetSalary', 'Net salary', inc.get('NetSalary'), c['salary']['netSalary'])
    check(
        'ITR1_IncomeDeductions.DeductionUs16',
        'Deductions u/s 16',
        inc.get('DeductionUs16'),
        c['salary']['deductionUs16'],
    )
    check(
        'ITR1_IncomeDeductions.IncomeFromSal',
        "Income chargeable under 'Salaries'",
        inc.get('IncomeFromSal'),
        c['salary']['incomeFromSalary'],
    )
    check(
        'ITR1_IncomeDeductions.TotalIncomeChargeableUnHP',
        "Income chargeable under 'House Property'",
        inc.get('TotalIncomeChargeableUnHP'),
        c['houseProperty']['incomeForGti'],
    )
    check(
        'ITR1_IncomeDeductions.IncomeOthSrc',
        "Income chargeable under 'Other Sources'",
        inc.get('IncomeOthSrc'),
        c['otherSources']['netIncomeOthSrc'],
    )
    check(
        'ITR1_IncomeDeductions.GrossTotIncome',
        'Gross total income',
        inc.get('GrossTotIncome'),
        c['grossTotalIncome'],
    )
    check(
        'ITR1_IncomeDeductions.GrossTotIncomeIncLTCG112A',
        'Gross total income including LTCG u/s 112A',
        inc.get('GrossTotIncomeIncLTCG112A'),
        c['grossTotalIncomeInclLtcg'],
    )
    check(
        'ITR1_IncomeDeductions.DeductUndChapVIA.TotalChapVIADeductions',
        'Total Chapter VI-A deductions',
        _obj(inc.get('DeductUndChapVIA')).get('TotalChapVIADeductions'),
        c['totalDeductions'],
    )
    check('ITR1_IncomeDeductions.TotalIncome', 'Total income', inc.get('TotalIncome'), c['totalIncome'])
    check(
        'ITR1_TaxComputation.TotalTaxPayable',
        'Tax payable on total income',
        tc.get('TotalTaxPayable'),
        c['tax']['taxPayableOnTotalIncome'],
    )
    check('ITR1_TaxComputation.Rebate87A', 'Rebate u/s 87A', tc.get('Rebate87A'), c['tax']['rebate87A'])
    check(
        'ITR1_TaxComputation.EducationCess',
        'Health and education cess',
        tc.get('EducationCess'),
        c['tax']['educationCess'],
    )
    check(
        'ITR1_TaxComputation.GrossTaxLiability',
        'Total tax and cess',
        tc.get('GrossTaxLiability'),
        c['tax']['totalTaxAndCess'],
    )
    check(
        'ITR1_TaxComputation.IntrstPay.IntrstPayUs234C',
        'Interest u/s 234C',
        ip.get('IntrstPayUs234C'),
        c['interest']['interest234C'],
    )
    check(
        'ITR1_TaxComputation.IntrstPay.FeeFurnish234I',
        'Fee u/s 234-I',
        ip.get('FeeFurnish234I'),
        c['interest']['fee234I'],
    )
    check(
        'ITR1_TaxComputation.TotTaxPlusIntrstPay',
        'Total tax, fee and interest',
        tc.get('TotTaxPlusIntrstPay'),
        c['totalTaxFeeAndInterest'],
    )
    check(
        'TaxPaid.TaxesPaid.TotalTaxesPaid',
        'Total taxes paid',
        _obj(_obj(p.get('TaxPaid')).get('TaxesPaid')).get('TotalTaxesPaid'),
        c['taxesPaid']['total'],
    )
    check('Refund.RefundDue', 'Refund due', _obj(p.get('Refund')).get('RefundDue'), c['refundDue'])
    check(
        'TaxPaid.BalTaxPayable',
        'Balance tax payable',
        _obj(p.get('TaxPaid')).get('BalTaxPayable'),
        c['balanceTaxPayable'],
    )

    return ImportResult(model=m, discrepancies=discrepancies, unmappedElements=unmapped_elements)
