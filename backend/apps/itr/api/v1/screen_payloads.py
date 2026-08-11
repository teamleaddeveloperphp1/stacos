"""Validates + coerces a JSON request body into exactly the payload shape
itr.services.return_service.save_screen/confirm_screen expect, per screen.

Input coercion: the web path hands _apply_* functions Django cleaned_data
(dates already `date` objects, numbers already `int`, from Form.is_valid()).
A JSON API client sends `"2026-06-15"` and possibly `"50000"` as strings.
Rather than write a second, parallel coercion layer, every screen here
binds the JSON body straight to the SAME Form/row-form classes itr/forms.py
already defines for the web path -- Django's field.to_python() already
accepts either a string or an already-typed value for every field type
used here (DateField accepts a `date` or an ISO string; IntegerField
accepts an `int` or a numeric string; CheckboxInput's value_from_datadict
accepts a bool or "true"/"false"). One coercion path, reused, not two that
could drift -- see tests.itr.test_api_v1's dates-through-the-API test for
the empirical proof, not just this claim.

Each build_*_payload(data) returns (payload, errors). `payload` is the
dict save_screen/confirm_screen want when `errors` is empty; when `errors`
is non-empty, `payload` is None and the view returns 400 with `errors`
(a dict, DRF-error-shaped, e.g. {"personal_info": {"pan": [...]}}).
"""

from apps.itr.forms import (
    BankAccountForm,
    ChallanRowForm,
    Disability80DDUForm,
    ExemptAllowanceForm,
    ExemptIncomeForm,
    FilingSectionForm,
    HousePropertyForm,
    HraForm,
    LoanInterestRowForm,
    OtherSourceForm,
    PersonalInfoForm,
    Schedule80CCCRowForm,
    Schedule80CRowForm,
    Schedule80DForm,
    Schedule80GGARowForm,
    Schedule80GGCRowForm,
    Schedule80GRowForm,
    TaxLiabilityForm,
    Tds1RowForm,
    Tds2RowForm,
    Tds3RowForm,
    TcsRowForm,
    DeductionsForm,
    SalaryForm,
)


def _single(form_class, data, key):
    """Bind one Form to data.get(key) (default {}), returning (cleaned_data,
    errors_or_None)."""
    form = form_class(data=data.get(key) or {})
    if form.is_valid():
        return form.cleaned_data, None
    return None, form.errors


def _rows(row_form_class, data, key):
    """Bind one row-Form per item in data.get(key) (default []). Returns
    (list_of_cleaned_data, errors_or_None) -- errors is a list, index-
    aligned with the input, with `None` for rows that were fine."""
    raw_rows = data.get(key) or []
    if not isinstance(raw_rows, list):
        return None, {'non_field_errors': [f'"{key}" must be a list of rows.']}
    cleaned_rows = []
    row_errors = []
    any_error = False
    for row in raw_rows:
        form = row_form_class(data=row if isinstance(row, dict) else {})
        if form.is_valid():
            cleaned_rows.append(form.cleaned_data)
            row_errors.append(None)
        else:
            cleaned_rows.append(None)
            row_errors.append(form.errors)
            any_error = True
    if any_error:
        return None, row_errors
    return cleaned_rows, None


def build_filing_section_payload(data):
    cleaned, errors = _single(FilingSectionForm, {'x': data}, 'x')
    if errors:
        return None, errors
    return cleaned, None


def build_personal_info_payload(data):
    errors = {}
    personal_info, e = _single(PersonalInfoForm, data, 'personal_info')
    if e:
        errors['personal_info'] = e
    bank_accounts, e = _rows(BankAccountForm, data, 'bank_accounts')
    if e:
        errors['bank_accounts'] = e
    if errors:
        return None, errors
    return {'personal_info': personal_info, 'bank_accounts': bank_accounts}, None


def build_gti_payload(data):
    errors = {}
    salary, e = _single(SalaryForm, data, 'salary')
    if e:
        errors['salary'] = e
    hra, e = _single(HraForm, data, 'hra')
    if e:
        errors['hra'] = e
    allowances, e = _rows(ExemptAllowanceForm, data, 'allowances')
    if e:
        errors['allowances'] = e
    properties, e = _rows(HousePropertyForm, data, 'properties')
    if e:
        errors['properties'] = e
    other_sources, e = _rows(OtherSourceForm, data, 'other_sources')
    if e:
        errors['other_sources'] = e
    exempt_income, e = _rows(ExemptIncomeForm, data, 'exempt_income')
    if e:
        errors['exempt_income'] = e
    if errors:
        return None, errors
    return {
        'salary': salary, 'hra': hra, 'allowances': allowances, 'properties': properties,
        'other_sources': other_sources, 'exempt_income': exempt_income,
    }, None


def build_deductions_payload(data):
    errors = {}
    deductions, e = _single(DeductionsForm, data, 'deductions')
    if e:
        errors['deductions'] = e
    schedule_80c, e = _rows(Schedule80CRowForm, data, 'schedule_80c')
    if e:
        errors['schedule_80c'] = e
    schedule_80ccc, e = _rows(Schedule80CCCRowForm, data, 'schedule_80ccc')
    if e:
        errors['schedule_80ccc'] = e
    schedule_80d, e = _single(Schedule80DForm, data, 'schedule_80d')
    if e:
        errors['schedule_80d'] = e
    disability_80dd, e = _single(Disability80DDUForm, data, 'disability_80dd')
    if e:
        errors['disability_80dd'] = e
    disability_80u, e = _single(Disability80DDUForm, data, 'disability_80u')
    if e:
        errors['disability_80u'] = e
    schedule_80e, e = _rows(LoanInterestRowForm, data, 'schedule_80e')
    if e:
        errors['schedule_80e'] = e
    schedule_80ee, e = _rows(LoanInterestRowForm, data, 'schedule_80ee')
    if e:
        errors['schedule_80ee'] = e
    schedule_80eea, e = _rows(LoanInterestRowForm, data, 'schedule_80eea')
    if e:
        errors['schedule_80eea'] = e
    schedule_80eeb, e = _rows(LoanInterestRowForm, data, 'schedule_80eeb')
    if e:
        errors['schedule_80eeb'] = e
    schedule_80g, e = _rows(Schedule80GRowForm, data, 'schedule_80g')
    if e:
        errors['schedule_80g'] = e
    schedule_80gga, e = _rows(Schedule80GGARowForm, data, 'schedule_80gga')
    if e:
        errors['schedule_80gga'] = e
    schedule_80ggc, e = _rows(Schedule80GGCRowForm, data, 'schedule_80ggc')
    if e:
        errors['schedule_80ggc'] = e
    if errors:
        return None, errors
    return {
        'deductions': deductions, 'schedule_80c': schedule_80c, 'schedule_80ccc': schedule_80ccc,
        'schedule_80d': schedule_80d, 'disability_80dd': disability_80dd, 'disability_80u': disability_80u,
        'schedule_80e': schedule_80e, 'schedule_80ee': schedule_80ee, 'schedule_80eea': schedule_80eea,
        'schedule_80eeb': schedule_80eeb, 'schedule_80g': schedule_80g, 'schedule_80gga': schedule_80gga,
        'schedule_80ggc': schedule_80ggc,
    }, None


def build_tax_paid_payload(data):
    errors = {}
    tds1, e = _rows(Tds1RowForm, data, 'tds1')
    if e:
        errors['tds1'] = e
    tds2, e = _rows(Tds2RowForm, data, 'tds2')
    if e:
        errors['tds2'] = e
    tds3, e = _rows(Tds3RowForm, data, 'tds3')
    if e:
        errors['tds3'] = e
    tcs, e = _rows(TcsRowForm, data, 'tcs')
    if e:
        errors['tcs'] = e
    challans, e = _rows(ChallanRowForm, data, 'challans')
    if e:
        errors['challans'] = e
    if errors:
        return None, errors
    return {'tds1': tds1, 'tds2': tds2, 'tds3': tds3, 'tcs': tcs, 'challans': challans}, None


def build_tax_liability_payload(data):
    tax_liability, e = _single(TaxLiabilityForm, data, 'tax_liability')
    if e:
        return None, {'tax_liability': e}
    return {'tax_liability': tax_liability}, None


SCREEN_PAYLOAD_BUILDERS = {
    'PERSONAL_INFO': build_personal_info_payload,
    'GROSS_TOTAL_INCOME': build_gti_payload,
    'TOTAL_DEDUCTIONS': build_deductions_payload,
    'TAX_PAID': build_tax_paid_payload,
    'TAX_LIABILITY': build_tax_liability_payload,
}
