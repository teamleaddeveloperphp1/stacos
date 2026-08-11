"""Every operation the app can perform on a TaxReturn, callable from plain
Python -- no HttpRequest, no Django form object, no template context in any
signature. itr/views.py builds forms, validates them, and calls into this
module; a future REST API (or any other writer) calls the exact same
functions and gets the exact same behaviour.

Money is returned as plain integers. Formatting (₹, commas, format_indian)
is a presentation concern that belongs to whichever caller renders it.
"""

import copy
import dataclasses

from django.utils import timezone

from apps.itr.engine.compute import compute
from apps.itr.engine.derive import derive_schedule_totals
from apps.itr.engine.validate import validate
from apps.itr.forms import SCHEDULE_80G_BLOCK_MODEL_KEY, bank_accounts_structural_errors
from apps.itr.deep_links import resolve_deep_link
from apps.itr.model_blank import blank_address
from apps.itr.models import AuditLogEntry, TaxReturn
from apps.itr.pdf import render_computation_sheet_pdf, render_return_preview_pdf, render_validation_report_pdf
from apps.itr.serialize.generate import generate_json, generate_json_or_throw
from apps.itr.serialize.importer import import_from_json
from apps.itr.util.model_diff import diff_model


class VersionConflictError(Exception):
    """Raised by save_screen/confirm_screen when the caller's expected
    version is stale -- someone else's edit landed first. Carries the same
    "edited by {who} at {when}" message the web UI has always shown; views
    catch this and render it, an API catches it and returns 409."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _get_owned_return(return_id, user):
    """Every entry point below is owner-scoped this same way -- there is no
    function in this module that can touch a return that isn't the caller's.
    Raises TaxReturn.DoesNotExist (framework-free) if not found/not owned;
    callers map that to a 404 however their transport wants to."""
    return TaxReturn.objects.get(pk=return_id, owner=user)


def _ensure_version(tax_return, expected_version):
    """§3.3 optimistic locking: the caller passes the draft version it last
    saw; if the stored version has moved on since, someone else's edit would
    otherwise be silently overwritten."""
    if expected_version is None or tax_return.version == expected_version:
        return
    last = tax_return.audit_log.exclude(kind=AuditLogEntry.KIND_VALIDATION_RUN).first()
    who = last.actor.username if last and last.actor else 'someone'
    when = last.at.strftime('%H:%M') if last else 'a moment ago'
    raise VersionConflictError(
        f'This return was edited by {who} at {when} since you opened it. '
        'Reload the page to see the latest version before continuing.'
    )


def _log_audit_diff(tax_return, before, after, actor):
    """Architecture mandate 6: every field change is audited (who, when, old
    value, new value). `before`/`after` are ReturnModel dict snapshots taken
    around a single screen's save."""
    entries = [
        AuditLogEntry(
            tax_return=tax_return, actor=actor, kind=AuditLogEntry.KIND_FIELD_CHANGE,
            field_path=path, old_value=old_value, new_value=new_value,
        )
        for path, old_value, new_value in diff_model(before, after)
    ]
    if entries:
        AuditLogEntry.objects.bulk_create(entries)


def _set_screen_status(model, screen, status):
    model.setdefault('screenStatus', {})[screen] = status


def _finding_to_dict(finding):
    # goto_url is a declared field on Finding (itr.engine.validate) -- asdict
    # picks it up like every other field, filled in or still None.
    return dataclasses.asdict(finding)


def report_to_dict(report):
    return {
        'ok': report.ok,
        'errors': [_finding_to_dict(f) for f in report.errors],
        'advisories': [_finding_to_dict(f) for f in report.advisories],
        'documentAdvisories': [_finding_to_dict(f) for f in report.documentAdvisories],
        'ruleErrors': list(report.ruleErrors),
        'tier': report.tier,
        'screen': report.screen,
        'ruleSetVersion': report.ruleSetVersion,
        'constantsVersion': report.constantsVersion,
        'rulesEvaluated': report.rulesEvaluated,
        'rulesSkipped': report.rulesSkipped,
        'evaluatedAt': report.evaluatedAt,
    }


# ---------------------------------------------------------------------------
# Per-screen apply functions -- moved from itr/views.py, unchanged in
# behaviour. Where a view used to iterate a Django formset's forms directly,
# it now passes `[f.cleaned_data for f in formset]` (every form's cleaned
# data, in formset order, NOT pre-filtered for DELETE/blank rows).
#
# That "not pre-filtered" is deliberate and departs from the plan's own
# `[f.cleaned_data for f in formset if f.cleaned_data and not
# f.cleaned_data.get('DELETE')]` suggestion: every one of these functions
# uses `prior = existing[i]` to recover fields the form doesn't expose
# (insurers, coOwners, schedule24B, typeOfIdentifier, ...). `existing[i]`
# only lines up with the right prior row because `i` is the row's position
# in the *rendered* formset, which matches its position in `existing` at
# load time -- deleting/blanking a row does not renumber the forms after it
# in the same submission. Pre-filtering before this loop compacts the
# indices and would silently pair a row with the wrong prior sibling
# whenever an earlier row was deleted or left blank. So the two skip checks
# (blank/DELETE, then "is this row meaningfully empty") both stay inside
# the function, exactly as before -- only the type changed, Form -> dict.
# ---------------------------------------------------------------------------

def _address_from_form(cleaned, prefix=''):
    return {
        'flatDoorBuilding': cleaned[f'{prefix}flat_door_building'],
        'premiseBuildingName': cleaned[f'{prefix}premise_building_name'],
        'roadStreet': cleaned[f'{prefix}road_street'],
        'areaLocality': cleaned[f'{prefix}area_locality'],
        'townCityDistrict': cleaned[f'{prefix}town_city_district'],
        'stateCode': cleaned[f'{prefix}state_code'],
        'countryCode': '91',
        'pinCode': cleaned[f'{prefix}pin_code'],
        'zipCode': '',
    }


def apply_personal_info_form(model, cleaned):
    pi = model['personalInfo']
    pi['firstName'] = cleaned['first_name']
    pi['middleName'] = cleaned['middle_name']
    pi['lastName'] = cleaned['last_name']
    pi['pan'] = cleaned['pan']
    pi['dob'] = cleaned['dob'].isoformat() if cleaned['dob'] else ''
    pi['aadhaar'] = cleaned['aadhaar']
    pi['employerCategory'] = cleaned['employer_category']
    pi['contact']['primaryMobile'] = cleaned['primary_mobile']
    pi['contact']['secondaryMobile'] = cleaned['secondary_mobile']
    pi['contact']['primaryEmail'] = cleaned['primary_email']
    pi['contact']['secondaryEmail'] = cleaned['secondary_email']
    pi['primaryAddress'] = _address_from_form(cleaned)
    pi['secondaryAddressSameAsPrimary'] = cleaned['secondary_address_same_as_primary']
    pi['secondaryAddress'] = dict(pi['primaryAddress']) if cleaned['secondary_address_same_as_primary'] == 'Y' else pi['secondaryAddress']

    fs = model['filingStatus']
    fs['origReturnAckNo'] = cleaned.get('orig_return_ack_no') or ''
    fs['origReturnFiledDate'] = cleaned['orig_return_filed_date'].isoformat() if cleaned.get('orig_return_filed_date') else ''
    fs['origReturnFileSec'] = cleaned.get('orig_return_file_sec')
    fs['a23ResponsesOriginal'] = cleaned.get('a23_responses_original') or ''
    fs['a23ResponsesCurrent'] = cleaned.get('a23_responses_current') or ''
    fs['seventhProviso139'] = cleaned.get('seventh_proviso_139') or 'N'
    fs['seventhProviso'] = {
        'travelExpenseAbove2Lakh': cleaned.get('travel_expense_above_2lakh') or 'N',
        'travelExpenseAmount': cleaned.get('travel_expense_amount'),
        'electricityAbove1Lakh': cleaned.get('electricity_above_1lakh') or 'N',
        'electricityAmount': cleaned.get('electricity_amount'),
        'clauseIvApplies': cleaned.get('clause_iv_applies') or 'N',
        'clauseIvDetails': fs['seventhProviso'].get('clauseIvDetails', []),
    }
    fs['representativeAssesseeFlag'] = cleaned.get('representative_assessee_flag') or 'N'
    if fs['representativeAssesseeFlag'] == 'Y':
        fs['representativeAssessee'] = {
            'name': cleaned.get('representative_name') or '',
            'email': cleaned.get('representative_email') or '',
            'mobile': cleaned.get('representative_mobile') or '',
            'pan': (cleaned.get('representative_pan') or '').upper(),
            'capacityOther': cleaned.get('representative_capacity_other') or '',
        }
    else:
        fs['representativeAssessee'] = None

    model['verification']['capacity'] = cleaned.get('verification_capacity') or 'S'


def apply_bank_accounts(model, rows):
    accounts = []
    existing = model.get('bankAccounts', [])
    for i, cleaned in enumerate(rows):
        if not cleaned or cleaned.get('DELETE'):
            continue
        if not cleaned.get('ifsc'):
            continue
        prior = existing[i] if i < len(existing) else {}
        ifsc = cleaned['ifsc'].strip().upper()
        bank_name = cleaned.get('bank_name') or prior.get('bankName', '')

        accounts.append({
            'id': prior.get('id') or f'bank-{i + 1}',
            'ifsc': ifsc,
            'bankName': bank_name,
            'accountNumber': cleaned['account_number'],
            'accountType': cleaned['account_type'],
            'nominateForRefund': cleaned['nominate_for_refund'],
        })
    model['bankAccounts'] = accounts


def apply_gti_forms(model, salary_cleaned, hra_cleaned, allowance_rows, property_rows, other_source_rows, exempt_income_rows):
    inc = model['income']

    inc['salary17_1'] = salary_cleaned['salary17_1']
    inc['perquisites17_2'] = salary_cleaned['perquisites17_2']
    inc['profitsInLieu17_3'] = salary_cleaned['profits_in_lieu17_3']
    inc['entertainmentAllowance16ii'] = salary_cleaned['entertainment_allowance_16ii'] or 0
    inc['professionalTax16iii'] = salary_cleaned['professional_tax_16iii'] or 0

    inc['hra10_13A'] = {
        'placeOfWork': hra_cleaned.get('place_of_work') or '',
        'actualHraReceived': hra_cleaned.get('actual_hra_received') or 0,
        'actualRentPaid': hra_cleaned.get('actual_rent_paid') or 0,
        'salary17_1': salary_cleaned['salary17_1'],
        'basicSalary': hra_cleaned.get('basic_salary') or 0,
        'dearnessAllowance': hra_cleaned.get('dearness_allowance') or 0,
    }

    existing_allowances = inc.get('exemptAllowances', [])
    allowances = []
    for i, cleaned in enumerate(allowance_rows):
        if not cleaned or cleaned.get('DELETE'):
            continue
        if not cleaned.get('nature'):
            continue
        prior = existing_allowances[i] if i < len(existing_allowances) else {}
        allowances.append({
            'id': prior.get('id') or f'allow-{i + 1}',
            'nature': cleaned['nature'],
            'amount': cleaned.get('amount') or 0,
        })
    inc['exemptAllowances'] = allowances

    existing_properties = inc.get('properties', [])
    properties = []
    for i, cleaned in enumerate(property_rows):
        if not cleaned or cleaned.get('DELETE'):
            continue
        if not cleaned.get('property_type'):
            continue
        prior = existing_properties[i] if i < len(existing_properties) else {}
        address = prior.get('address') or blank_address()
        address = {
            **address,
            'flatDoorBuilding': cleaned.get('flat_door_building') or address.get('flatDoorBuilding', ''),
            'areaLocality': cleaned.get('area_locality') or address.get('areaLocality', ''),
            'townCityDistrict': cleaned.get('town_city_district') or address.get('townCityDistrict', ''),
            'stateCode': cleaned.get('state_code') or address.get('stateCode', ''),
            'pinCode': cleaned.get('pin_code') or address.get('pinCode', ''),
        }
        properties.append({
            'id': prior.get('id') or f'hp-{i + 1}',
            'address': address,
            'propertyOwner': cleaned.get('property_owner') or prior.get('propertyOwner', ''),
            'propertyOwnerOther': prior.get('propertyOwnerOther', ''),
            'propertyType': cleaned['property_type'],
            'coOwned': cleaned.get('co_owned') or 'N',
            'assesseeSharePercent': cleaned.get('assessee_share_percent') or 0,
            'coOwners': prior.get('coOwners', []),
            'tenants': prior.get('tenants', []),
            'grossRent': cleaned.get('gross_rent') or 0,
            'localTaxes': cleaned.get('local_taxes') or 0,
            'rentNotRealized': cleaned.get('rent_not_realized') or 0,
            'interestOnBorrowedCapital': cleaned.get('interest_on_borrowed_capital') or 0,
            'schedule24B': prior.get('schedule24B', []),
            'arrearsUnrealisedRentReceived': prior.get('arrearsUnrealisedRentReceived', 0),
        })
    inc['properties'] = properties

    existing_other_sources = inc.get('otherSources', [])
    other_sources = []
    for i, cleaned in enumerate(other_source_rows):
        if not cleaned or cleaned.get('DELETE'):
            continue
        if not cleaned.get('nature'):
            continue
        prior = existing_other_sources[i] if i < len(existing_other_sources) else {}
        other_sources.append({
            'id': prior.get('id') or f'os-{i + 1}',
            'nature': cleaned['nature'],
            'otherNatureDescription': prior.get('otherNatureDescription', ''),
            'amount': cleaned.get('amount') or 0,
            'dividendQuarterly': prior.get('dividendQuarterly'),
        })
    inc['otherSources'] = other_sources

    existing_exempt_income = inc.get('exemptIncome', [])
    exempt_income = []
    for i, cleaned in enumerate(exempt_income_rows):
        if not cleaned or cleaned.get('DELETE'):
            continue
        if not cleaned.get('category') and not cleaned.get('sub_category'):
            continue
        prior = existing_exempt_income[i] if i < len(existing_exempt_income) else {}
        exempt_income.append({
            'id': prior.get('id') or f'ei-{i + 1}',
            'category': cleaned.get('category') or '',
            'subCategory': cleaned.get('sub_category') or '',
            'description': cleaned.get('description') or '',
            'amount': cleaned.get('amount') or 0,
        })
    inc['exemptIncome'] = exempt_income


def apply_deductions_forms(model, cleaned, sched80c_rows, sched80ccc_rows, sched80d_cleaned,
                            disability_80dd_cleaned, disability_80u_cleaned,
                            sched80e_rows, sched80ee_rows, sched80eea_rows, sched80eeb_rows,
                            sched80g_rows, sched80gga_rows, sched80ggc_rows):
    d = model['deductions']

    # --- Schedule 80C / 80CCC: s80C and s80CCC are derived (not user fields)
    # because tier-2 rules A-241/A-301-339 require an exact match to the
    # schedule total (see itr.engine.derive.derive_schedule_totals below).
    existing = d.get('schedule80C', [])
    rows = []
    for i, row_cleaned in enumerate(sched80c_rows):
        if not row_cleaned or row_cleaned.get('DELETE'):
            continue
        if not row_cleaned.get('identification_no') and not row_cleaned.get('amount'):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'80c-{i + 1}',
            'typeOfIdentifier': prior.get('typeOfIdentifier', ''),
            'identificationNo': row_cleaned.get('identification_no') or '',
            'amount': row_cleaned.get('amount') or 0,
        })
    d['schedule80C'] = rows

    existing = d.get('pensionContribution80CCC', [])
    rows = []
    for i, row_cleaned in enumerate(sched80ccc_rows):
        if not row_cleaned or row_cleaned.get('DELETE'):
            continue
        if not row_cleaned.get('name_of_identifier') and not row_cleaned.get('amount'):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'80ccc-{i + 1}',
            'typeOfIdentifier': prior.get('typeOfIdentifier', ''),
            'nameOfIdentifier': row_cleaned.get('name_of_identifier') or '',
            'amount': row_cleaned.get('amount') or 0,
        })
    d['pensionContribution80CCC'] = rows

    d['s80CCD1'] = cleaned.get('s80CCD1') or 0
    d['pranNumbers'] = [p.strip() for p in (cleaned.get('pran_numbers') or '').split(',') if p.strip()]
    d['s80CCD1B'] = cleaned.get('s80CCD1B') or 0
    d['s80CCD2'] = cleaned.get('s80CCD2') or 0
    d['s80CCH'] = cleaned.get('s80CCH') or 0

    # --- 80D: fixed 4-block structure; s80D stays a genuine user field (only
    # needs to be <= the schedule's eligible amount, not an exact match).
    prior_80d = d['schedule80D']
    c = sched80d_cleaned
    d['schedule80D'] = {
        'selfFamilySeniorFlag': c.get('self_family_senior_flag') or '',
        'selfFamily': {
            'healthInsurancePremium': c.get('self_family_health_insurance_premium') or 0,
            'insurers': prior_80d['selfFamily'].get('insurers', []),
            'preventiveHealthCheckup': c.get('self_family_preventive_health_checkup') or 0,
            'medicalExpenditure': c.get('self_family_medical_expenditure') or 0,
        },
        'selfFamilySenior': {
            'healthInsurancePremium': c.get('self_family_senior_health_insurance_premium') or 0,
            'insurers': prior_80d['selfFamilySenior'].get('insurers', []),
            'preventiveHealthCheckup': c.get('self_family_senior_preventive_health_checkup') or 0,
            'medicalExpenditure': c.get('self_family_senior_medical_expenditure') or 0,
        },
        'parentsSeniorFlag': c.get('parents_senior_flag') or '',
        'parents': {
            'healthInsurancePremium': c.get('parents_health_insurance_premium') or 0,
            'insurers': prior_80d['parents'].get('insurers', []),
            'preventiveHealthCheckup': c.get('parents_preventive_health_checkup') or 0,
            'medicalExpenditure': c.get('parents_medical_expenditure') or 0,
        },
        'parentsSenior': {
            'healthInsurancePremium': c.get('parents_senior_health_insurance_premium') or 0,
            'insurers': prior_80d['parentsSenior'].get('insurers', []),
            'preventiveHealthCheckup': c.get('parents_senior_preventive_health_checkup') or 0,
            'medicalExpenditure': c.get('parents_senior_medical_expenditure') or 0,
        },
    }
    d['s80D'] = cleaned.get('s80D') or 0

    # --- 80DD / 80U: s80DD/s80U are derived from the schedule's `amount`
    # because tier-2 rules require an exact match (A-201-300).
    def apply_disability(section_cleaned, prior_sched):
        return {
            'natureOfDisability': section_cleaned.get('nature_of_disability') or '',
            'typeOfDisability': section_cleaned.get('type_of_disability') or '',
            'amount': section_cleaned.get('amount') or 0,
            'dependentType': prior_sched.get('dependentType', ''),
            'dependentPan': prior_sched.get('dependentPan', ''),
            'dependentAadhaar': prior_sched.get('dependentAadhaar', ''),
            'form10IAFiled': section_cleaned.get('form10IAFiled') or False,
            'form10IAAckNo': section_cleaned.get('form10IAAckNo') or '',
            'udidNo': prior_sched.get('udidNo', ''),
        }

    d['schedule80DD'] = apply_disability(disability_80dd_cleaned, d['schedule80DD'])
    d['schedule80U'] = apply_disability(disability_80u_cleaned, d['schedule80U'])

    d['s80DDB'] = cleaned.get('s80DDB') or 0
    d['s80DDBUsrType'] = cleaned.get('s80DDBUsrType') or ''
    d['s80DDBDisease'] = cleaned.get('s80DDBDisease') or ''

    # --- Loan-interest schedules (80E / 80EE / 80EEA / 80EEB): s80E/s80EE/
    # s80EEA/s80EEB are derived from the schedule total for the same reason
    # as 80C/80CCC above.
    def apply_loan_rows(loan_row_dicts, existing_rows, prefix):
        loan_rows = []
        for i, row_cleaned in enumerate(loan_row_dicts):
            if not row_cleaned or row_cleaned.get('DELETE'):
                continue
            if not row_cleaned.get('lender_name') and not row_cleaned.get('loan_account_no') and not row_cleaned.get('interest'):
                continue
            prior = existing_rows[i] if i < len(existing_rows) else {}
            loan_rows.append({
                'id': prior.get('id') or f'{prefix}-{i + 1}',
                'loanTakenFrom': prior.get('loanTakenFrom', ''),
                'lenderName': row_cleaned.get('lender_name') or '',
                'loanAccountNo': row_cleaned.get('loan_account_no') or '',
                'dateOfLoan': row_cleaned['date_of_loan'].isoformat() if row_cleaned.get('date_of_loan') else '',
                'totalLoanAmount': prior.get('totalLoanAmount', 0),
                'loanOutstandingAmount': prior.get('loanOutstandingAmount', 0),
                'interest': row_cleaned.get('interest') or 0,
                'vehicleRegNo': prior.get('vehicleRegNo'),
            })
        return loan_rows

    d['schedule80E'] = apply_loan_rows(sched80e_rows, d.get('schedule80E', []), '80e')
    d['schedule80EE'] = apply_loan_rows(sched80ee_rows, d.get('schedule80EE', []), '80ee')
    d['schedule80EEA'] = apply_loan_rows(sched80eea_rows, d.get('schedule80EEA', []), '80eea')
    d['schedule80EEB'] = apply_loan_rows(sched80eeb_rows, d.get('schedule80EEB', []), '80eeb')
    d['stampDutyValue80EEA'] = cleaned.get('stampDutyValue80EEA') or 0

    # --- 80G: one combined formset with a block selector standing in for the
    # 4 separate CBDT tables (Don100Percent / Don50PercentNoApprReqd / ...).
    new_sched80g = {model_key: [] for model_key in SCHEDULE_80G_BLOCK_MODEL_KEY.values()}
    for i, row_cleaned in enumerate(sched80g_rows):
        if not row_cleaned or row_cleaned.get('DELETE'):
            continue
        if not any([
            row_cleaned.get('donee_name'), row_cleaned.get('pan'),
            row_cleaned.get('donation_cash'), row_cleaned.get('donation_other_mode'),
        ]):
            continue
        block = row_cleaned.get('block') or 'A'
        model_key = SCHEDULE_80G_BLOCK_MODEL_KEY.get(block, 'don100Percent')
        ifsc = (row_cleaned.get('ifsc') or '').strip().upper()
        new_sched80g[model_key].append({
            'id': f'80g-{i + 1}',
            'name': row_cleaned.get('donee_name') or '',
            'pan': (row_cleaned.get('pan') or '').upper(),
            'arnNo': '',
            'address': blank_address(),
            'donationCash': row_cleaned.get('donation_cash') or 0,
            'donationOtherMode': row_cleaned.get('donation_other_mode') or 0,
            'transactionRefNo': row_cleaned.get('transaction_ref_no') or '',
            'ifsc': ifsc,
        })
    d['schedule80G'] = new_sched80g
    d['s80G'] = cleaned.get('s80G') or 0

    existing = d.get('schedule80GGA', [])
    rows = []
    for i, row_cleaned in enumerate(sched80gga_rows):
        if not row_cleaned or row_cleaned.get('DELETE'):
            continue
        if not any([row_cleaned.get('donee_name'), row_cleaned.get('donation_cash'), row_cleaned.get('donation_other_mode')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'gga-{i + 1}',
            'relevantClause': prior.get('relevantClause', ''),
            'name': row_cleaned.get('donee_name') or '',
            'pan': (row_cleaned.get('pan') or '').upper(),
            'address': prior.get('address') or blank_address(),
            'donationCash': row_cleaned.get('donation_cash') or 0,
            'donationOtherMode': row_cleaned.get('donation_other_mode') or 0,
        })
    d['schedule80GGA'] = rows
    d['s80GGA'] = cleaned.get('s80GGA') or 0

    existing = d.get('schedule80GGC', [])
    rows = []
    for i, row_cleaned in enumerate(sched80ggc_rows):
        if not row_cleaned or row_cleaned.get('DELETE'):
            continue
        if not any([row_cleaned.get('political_party_name'), row_cleaned.get('donation_cash'), row_cleaned.get('donation_other_mode')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        ifsc = (row_cleaned.get('ifsc') or '').strip().upper()
        rows.append({
            'id': prior.get('id') or f'ggc-{i + 1}',
            'donationDate': row_cleaned['donation_date'].isoformat() if row_cleaned.get('donation_date') else '',
            'politicalPartyName': row_cleaned.get('political_party_name') or '',
            'politicalPartyPan': (row_cleaned.get('political_party_pan') or '').upper(),
            'donationCash': row_cleaned.get('donation_cash') or 0,
            'donationOtherMode': row_cleaned.get('donation_other_mode') or 0,
            'transactionRefNo': row_cleaned.get('transaction_ref_no') or '',
            'ifsc': ifsc,
        })
    d['schedule80GGC'] = rows
    d['s80GGC'] = cleaned.get('s80GGC') or 0

    d['s80GG'] = cleaned.get('s80GG') or 0
    d['form10BAFiled'] = cleaned.get('form10BAFiled') or False
    d['form10BAAckNo'] = cleaned.get('form10BAAckNo') or ''

    d['s80TTA'] = cleaned.get('s80TTA') or 0
    d['s80TTB'] = cleaned.get('s80TTB') or 0

    derive_schedule_totals(model)


def apply_tax_paid_forms(model, tds1_rows, tds2_rows, tds3_rows, tcs_rows, challan_rows):
    tp = model['taxPaid']

    existing = tp.get('tds1', [])
    rows = []
    for i, c in enumerate(tds1_rows):
        if not c or c.get('DELETE'):
            continue
        if not c.get('tan') and not c.get('deductor_name') and not c.get('income_chargeable_salary') and not c.get('total_tax_deducted'):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'tds1-{i + 1}',
            'tan': c.get('tan') or '',
            'deductorName': c.get('deductor_name') or '',
            'incomeChargeableSalary': c.get('income_chargeable_salary') or 0,
            'totalTaxDeducted': c.get('total_tax_deducted') or 0,
        })
    tp['tds1'] = rows

    existing = tp.get('tds2', [])
    rows = []
    for i, c in enumerate(tds2_rows):
        if not c or c.get('DELETE'):
            continue
        if not any([c.get('tan_or_pan'), c.get('deductor_name'), c.get('gross_receipt'), c.get('tax_deducted')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'tds2-{i + 1}',
            'tanOrPan': c.get('tan_or_pan') or '',
            'deductorName': c.get('deductor_name') or '',
            'grossReceipt': c.get('gross_receipt') or 0,
            'deductedYear': c.get('deducted_year') or '',
            'taxDeducted': c.get('tax_deducted') or 0,
            'tdsClaimedThisYear': c.get('tds_claimed_this_year') or 0,
            'tdsSection': c.get('tds_section') or '',
            'headOfIncome': c.get('head_of_income') or '',
        })
    tp['tds2'] = rows

    existing = tp.get('tds3', [])
    rows = []
    for i, c in enumerate(tds3_rows):
        if not c or c.get('DELETE'):
            continue
        if not any([c.get('pan_of_tenant'), c.get('name_of_tenant'), c.get('gross_receipt'), c.get('tax_deducted')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'tds3-{i + 1}',
            'panOfTenant': c.get('pan_of_tenant') or '',
            'aadhaarOfTenant': c.get('aadhaar_of_tenant') or '',
            'nameOfTenant': c.get('name_of_tenant') or '',
            'grossReceipt': c.get('gross_receipt') or 0,
            'deductedYear': c.get('deducted_year') or '',
            'taxDeducted': c.get('tax_deducted') or 0,
            'tdsClaimedThisYear': c.get('tds_claimed_this_year') or 0,
            'tdsSection': c.get('tds_section') or '',
            'headOfIncome': c.get('head_of_income') or '',
        })
    tp['tds3'] = rows

    existing = tp.get('tcs', [])
    rows = []
    for i, c in enumerate(tcs_rows):
        if not c or c.get('DELETE'):
            continue
        if not any([c.get('tan'), c.get('collector_name'), c.get('tax_collected')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'tcs-{i + 1}',
            'tan': c.get('tan') or '',
            'collectorName': c.get('collector_name') or '',
            'taxCollected': c.get('tax_collected') or 0,
            'collectedYear': c.get('collected_year') or '',
            'totalTcs': prior.get('totalTcs', 0),
            'tcsClaimedThisYear': c.get('tcs_claimed_this_year') or 0,
        })
    tp['tcs'] = rows

    existing = tp.get('challans', [])
    rows = []
    for i, c in enumerate(challan_rows):
        if not c or c.get('DELETE'):
            continue
        if not any([c.get('bsr_code'), c.get('challan_serial_no'), c.get('amount')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        rows.append({
            'id': prior.get('id') or f'chl-{i + 1}',
            'bsrCode': c.get('bsr_code') or '',
            'dateOfDeposit': c['date_of_deposit'].isoformat() if c.get('date_of_deposit') else '',
            'challanSerialNo': c.get('challan_serial_no') or '',
            'amount': c.get('amount') or 0,
        })
    tp['challans'] = rows


def apply_tax_liability_form(model, cleaned):
    tl = model['taxLiability']
    tl['relief89'] = cleaned.get('relief89') or 0
    tl['form10EFiled'] = cleaned.get('form10EFiled') or False
    tl['form10EAckNo'] = cleaned.get('form10EAckNo') or ''
    # Left blank -> None, meaning "use the engine's computed default" (see
    # forms.py's TaxLiabilityForm docstring); an explicit value overrides it.
    tl['interest234AOverride'] = cleaned.get('interest234AOverride')
    tl['interest234BOverride'] = cleaned.get('interest234BOverride')
    tl['fee234FOverride'] = cleaned.get('fee234FOverride')


def _apply_personal_info_screen(model, payload):
    apply_personal_info_form(model, payload['personal_info'])
    apply_bank_accounts(model, payload['bank_accounts'])


def _apply_gti_screen(model, payload):
    apply_gti_forms(
        model, payload['salary'], payload['hra'], payload['allowances'],
        payload['properties'], payload['other_sources'], payload['exempt_income'],
    )


def _apply_deductions_screen(model, payload):
    apply_deductions_forms(
        model, payload['deductions'], payload['schedule_80c'], payload['schedule_80ccc'],
        payload['schedule_80d'], payload['disability_80dd'], payload['disability_80u'],
        payload['schedule_80e'], payload['schedule_80ee'], payload['schedule_80eea'], payload['schedule_80eeb'],
        payload['schedule_80g'], payload['schedule_80gga'], payload['schedule_80ggc'],
    )


def _apply_tax_paid_screen(model, payload):
    apply_tax_paid_forms(
        model, payload['tds1'], payload['tds2'], payload['tds3'], payload['tcs'], payload['challans'],
    )


def _apply_tax_liability_screen(model, payload):
    apply_tax_liability_form(model, payload['tax_liability'])


_SCREEN_HANDLERS = {
    'PERSONAL_INFO': _apply_personal_info_screen,
    'GROSS_TOTAL_INCOME': _apply_gti_screen,
    'TOTAL_DEDUCTIONS': _apply_deductions_screen,
    'TAX_PAID': _apply_tax_paid_screen,
    'TAX_LIABILITY': _apply_tax_liability_screen,
}


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def get_return(return_id, user):
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    computed = compute(model)
    return {
        'id': str(tax_return.pk),
        'version': tax_return.version,
        'ay': model['ay'],
        'model': model,
        'computed': computed,
        'screen_status': model.get('screenStatus', {}),
        'updated_at': tax_return.updated_at,
    }


def save_screen(return_id, user, screen, payload, expected_version):
    tax_return = _get_owned_return(return_id, user)
    _ensure_version(tax_return, expected_version)
    model = tax_return.data

    before = copy.deepcopy(model)
    _SCREEN_HANDLERS[screen](model, payload)
    _log_audit_diff(tax_return, before, model, user)
    tax_return.bump_version()
    _set_screen_status(model, screen, 'IN_PROGRESS')
    tax_return.save()

    return {
        'version': tax_return.version,
        'screen_status': model.get('screenStatus', {}),
        'updated_at': tax_return.updated_at,
        'model': model,
        'computed': compute(model),
    }


def confirm_screen(return_id, user, screen, payload, expected_version):
    tax_return = _get_owned_return(return_id, user)
    _ensure_version(tax_return, expected_version)
    model = tax_return.data

    before = copy.deepcopy(model)
    _SCREEN_HANDLERS[screen](model, payload)
    _log_audit_diff(tax_return, before, model, user)
    tax_return.bump_version()

    computed = compute(model)
    report = validate(model, tier=2, screen=screen, computed=computed)
    # §4.6: at least one bank account, exactly one nominated -- a
    # screen-level product constraint, not a numbered CBDT rule, so it's
    # checked alongside (not inside) the rule registry, and only for
    # PERSONAL_INFO.
    bank_errors = bank_accounts_structural_errors(model.get('bankAccounts', [])) if screen == 'PERSONAL_INFO' else []

    has_errors = bool(report.errors) or bool(bank_errors)
    _set_screen_status(model, screen, 'HAS_ERRORS' if has_errors else 'CONFIRMED')
    tax_return.save()
    AuditLogEntry.objects.create(
        tax_return=tax_return, actor=user, kind=AuditLogEntry.KIND_VALIDATION_RUN,
        payload={'screen': screen, 'errors': [e.ruleId for e in report.errors], 'bankErrors': bank_errors},
    )

    return {
        'version': tax_return.version,
        'confirmed': not has_errors,
        'report': report_to_dict(report),
        'bank_errors': bank_errors,
        'updated_at': tax_return.updated_at,
        'model': model,
        'computed': computed,
    }


def get_computation(return_id, user):
    tax_return = _get_owned_return(return_id, user)
    return compute(tax_return.data)


def run_validation(return_id, user):
    """Tier-3 read-only validation, exactly as the Validation screen renders
    it: the full report, plus whether the JSON is downloadable right now
    (report.errors empty and every advisory acknowledged)."""
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    computed = compute(model)
    result = generate_json(model, {'computed': computed})
    report = result.validation
    for finding in report.errors + report.advisories + report.documentAdvisories:
        finding.goto_url = resolve_deep_link(return_id, finding.deepLink)

    return {
        'report': report_to_dict(report),
        'downloadable': result.downloadable and not result.pendingAcknowledgements,
        'pending_acknowledgements': list(result.pendingAcknowledgements),
    }


def generate_return_json(return_id, user):
    """Raises GenerationBlockedError if the return isn't in a downloadable
    state (unresolved errors or un-acknowledged advisories) -- generation is
    never silently forced through."""
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    computed = compute(model)
    result = generate_json_or_throw(model, {'computed': computed})
    AuditLogEntry.objects.create(
        tax_return=tax_return, actor=user, kind=AuditLogEntry.KIND_JSON_GENERATION,
        payload={'filename': result.filename, 'sha256': result.sha256}, new_value=model,
    )
    return {'filename': result.filename, 'sha256': result.sha256, 'json': result.json}


def import_return_json(return_id, user, payload):
    """Overwrites this return's data with what's in `payload` (a parsed
    CBDT-schema ITR-1 JSON document), deriving Chapter VI-A schedule totals
    fresh rather than trusting the document's own section-total fields (see
    itr.serialize.importer.import_from_json)."""
    tax_return = _get_owned_return(return_id, user)
    ctx = {'tenantId': str(user.pk), 'returnId': str(tax_return.pk)}
    result = import_from_json(payload, ctx)
    tax_return.data = result.model
    tax_return.data['tenantId'] = str(user.pk)
    tax_return.data['returnId'] = str(tax_return.pk)
    tax_return.bump_version()
    tax_return.save()
    return {
        'version': tax_return.version,
        'unmapped_elements': result.unmappedElements,
        'discrepancies': result.discrepancies,
    }


def acknowledge_advisories(return_id, user, rule_ids):
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    acks = model.setdefault('advisoryAcknowledgements', {})
    now_iso = timezone.now().isoformat()
    for rule_id in rule_ids:
        acks[rule_id] = {'by': user.username if user else 'demo', 'at': now_iso}
    tax_return.save()
    AuditLogEntry.objects.create(
        tax_return=tax_return, actor=user, kind=AuditLogEntry.KIND_ADVISORY_ACK,
        payload={'acknowledgedRuleIds': list(rule_ids)},
    )
    return {'acknowledged': list(rule_ids), 'version': tax_return.version}


def regime_comparison(return_id, user):
    """A neutral, no-recommendation side-by-side: tax payable under both
    regimes, computed live from the same model (addendum §1.3's "a neutral
    side-by-side calculator is acceptable" carve-out). Raw integers -- never
    formatted, never phrased as a recommendation."""
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    other = copy.deepcopy(model)
    other['filingStatus']['optOutOfNewRegime'] = 'N' if model['filingStatus']['optOutOfNewRegime'] == 'Y' else 'Y'
    this_computed = compute(model)
    other_computed = compute(other)
    by_regime = {this_computed['regime']: this_computed, other_computed['regime']: other_computed}
    return {
        'NEW': by_regime['NEW']['totalTaxFeeAndInterest'],
        'OLD': by_regime['OLD']['totalTaxFeeAndInterest'],
    }


def save_verification(return_id, user, cleaned):
    """The declaration on the Validation screen -- name/PAN/capacity/place of
    the person verifying the return. Small and single-screen enough that it
    doesn't need the save/confirm-with-tier-2-validation shape the seven
    numbered screens use; it's just a field write + audit diff."""
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    before = copy.deepcopy(model)
    v = model['verification']
    v['assesseeVerName'] = cleaned['assessee_ver_name']
    v['fatherName'] = cleaned['father_name']
    v['assesseeVerPan'] = cleaned['assessee_ver_pan'].upper()
    v['capacity'] = cleaned['capacity']
    v['place'] = cleaned['place']
    _log_audit_diff(tax_return, before, model, user)
    tax_return.bump_version()
    tax_return.save()
    return {'version': tax_return.version}


def confirm_tax_summary(return_id, user):
    """Tax Summary has no form of its own -- "Proceed" just marks it
    confirmed and moves on to Validation."""
    tax_return = _get_owned_return(return_id, user)
    _set_screen_status(tax_return.data, 'TAX_SUMMARY', 'CONFIRMED')
    tax_return.save()
    return {'version': tax_return.version}


def save_filing_section(return_id, user, cleaned, expected_version):
    """The gate screen before Personal Information: filing section + tax
    regime. Not one of the five _SCREEN_HANDLERS screens (no tier-2
    confirm gate, no schedule to derive) -- a plain field write + version
    check, same shape as save_verification."""
    tax_return = _get_owned_return(return_id, user)
    _ensure_version(tax_return, expected_version)
    fs = tax_return.data['filingStatus']
    fs['returnFileSec'] = cleaned['return_file_sec']
    fs['optOutOfNewRegime'] = cleaned['opt_out_of_new_regime']
    tax_return.bump_version()
    tax_return.save()
    return {'version': tax_return.version, 'model': tax_return.data, 'updated_at': tax_return.updated_at}


# ---------------------------------------------------------------------------
# PDF orchestration -- compute()/generate_json() + the raw dataclass report
# never leave this module. itr/pdf.py's renderers do attribute access on
# that dataclass (report.ok, report.errors, ...), so they stay untouched;
# only the two calls that produce it move behind the service boundary. Each
# of these is the ONLY place its respective report/computed figures get
# built for PDF purposes -- run_validation() builds its own for the web/API
# JSON response, so there is exactly one function per artifact, not two
# that could drift apart.
# ---------------------------------------------------------------------------

def export_validation_report_pdf(return_id, user):
    tax_return = _get_owned_return(return_id, user)
    model = tax_return.data
    computed = compute(model)
    result = generate_json(model, {'computed': computed})
    return render_validation_report_pdf(tax_return, result.validation)


def export_computation_sheet_pdf(return_id, user):
    tax_return = _get_owned_return(return_id, user)
    computed = compute(tax_return.data)
    return render_computation_sheet_pdf(tax_return, computed)


def export_return_preview_pdf(return_id, user):
    tax_return = _get_owned_return(return_id, user)
    computed = compute(tax_return.data)
    return render_return_preview_pdf(tax_return, computed)
