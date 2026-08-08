import copy

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from itr1.engine.compute import compute
from itr1.engine.validate import validate
from itr1.serialize.generate import GenerationBlockedError, generate_json, generate_json_or_throw
from itr1.services.ifsc_directory import ifsc_validator
from itr1.forms import (
    BankAccountFormSet,
    ChallanFormSet,
    bank_accounts_structural_errors,
    DeductionsForm,
    Disability80DDUForm,
    ExemptAllowanceFormSet,
    ExemptIncomeFormSet,
    HousePropertyFormSet,
    OtherSourceFormSet,
    PersonalInfoForm,
    RETURN_FILE_SEC_CHOICES,
    SCHEDULE_80G_BLOCK_MODEL_KEY,
    SalaryForm,
    Schedule80CCCFormSet,
    Schedule80CFormSet,
    Schedule80DForm,
    Schedule80EEAFormSet,
    Schedule80EEBFormSet,
    Schedule80EEFormSet,
    Schedule80EFormSet,
    Schedule80GFormSet,
    Schedule80GGAFormSet,
    Schedule80GGCFormSet,
    TaxLiabilityForm,
    TcsFormSet,
    Tds1FormSet,
    Tds2FormSet,
    Tds3FormSet,
)
from itr1.deep_links import resolve_deep_link
from itr1.model_blank import blank_address
from itr1.models import AuditLogEntry, TaxReturn
from itr1.pdf import render_computation_sheet_pdf, render_return_preview_pdf, render_validation_report_pdf
from itr1.rules.registry import RULE_SET_VERSION
from itr1.screens import build_menu_items
from itr1.serialize.json_schema_validator import SCHEMA_VERSION
from itr1.util.num import format_indian, format_rupees

_RETURN_FILE_SEC_LABELS = dict(RETURN_FILE_SEC_CHOICES)


def _chrome_context(tax_return, computed=None):
    """Global chrome shown on every screen (§3.3): taxpayer name/PAN/AY/filing
    section, the derived regime badge, a live refund/payable ticker, and the
    rule-set/schema/constants versions + draft save status for the footer."""
    model = tax_return.data
    computed = computed if computed is not None else compute(model)
    pi = model['personalInfo']
    name = ' '.join(x for x in (pi['firstName'], pi['middleName'], pi['lastName']) if x).strip()

    refund = computed.get('refundDue', 0) or 0
    payable = computed.get('balanceTaxPayable', 0) or 0
    if refund > 0:
        ticker = f'Refund due: {format_rupees(refund)}'
        ticker_class = 'refund'
    elif payable > 0:
        ticker = f'Tax payable: {format_rupees(payable)}'
        ticker_class = 'payable'
    else:
        ticker = 'No tax payable, no refund due'
        ticker_class = 'neutral'

    return {
        'taxpayer_name': name or 'Unnamed taxpayer',
        'taxpayer_pan': pi['pan'] or '—',
        'filing_section_label': _RETURN_FILE_SEC_LABELS.get(model['filingStatus']['returnFileSec'], '—'),
        'regime': computed.get('regime', 'NEW'),
        'ticker': ticker,
        'ticker_class': ticker_class,
        'rule_set_version': RULE_SET_VERSION,
        'constants_version': computed.get('constantsVersion', ''),
        'schema_version': SCHEMA_VERSION,
        'draft_version': tax_return.version,
        'draft_updated_at': tax_return.updated_at,
    }


def _current_user(request):
    """No login screen exists yet (out of scope for this phase) — fall back
    to a single auto-provisioned demo user so the screens are usable end to
    end. Replace with real auth in a later phase."""
    if request.user.is_authenticated:
        return request.user
    user, created = User.objects.get_or_create(username='demo')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return user


def set_locale(request, locale):
    """§13: English/Hindi UI toggle. Stores the choice in the session and
    bounces back to wherever the link was clicked from."""
    if locale in ('en', 'hi'):
        request.session['locale'] = locale
    return redirect(request.META.get('HTTP_REFERER') or 'itr1:return_list')


def return_list(request):
    user = _current_user(request)
    returns = TaxReturn.objects.filter(owner=user).order_by('-updated_at')

    cards = []
    for r in returns:
        chrome = _chrome_context(r)
        statuses = (r.data.get('screenStatus') or {}).values()
        confirmed_count = sum(1 for s in statuses if str(s).lower() == 'confirmed')
        cards.append({
            'obj': r,
            'taxpayer_name': chrome['taxpayer_name'],
            'taxpayer_pan': chrome['taxpayer_pan'],
            'regime': chrome['regime'],
            'ticker': chrome['ticker'],
            'ticker_class': chrome['ticker_class'],
            'confirmed_count': confirmed_count,
            'screen_total': 7,
        })

    return render(request, 'itr1/return_list.html', {'cards': cards})


def return_create(request):
    user = _current_user(request)
    tax_return = TaxReturn.objects.create(owner=user)
    return redirect('itr1:personal_info', return_id=tax_return.pk)


def _get_return(request, return_id):
    user = _current_user(request)
    return get_object_or_404(TaxReturn, pk=return_id, owner=user)


def _screen_status(tax_return):
    return tax_return.data.get('screenStatus', {})


def _set_screen_status(tax_return, screen_id, status):
    tax_return.data.setdefault('screenStatus', {})[screen_id] = status


def _is_ajax(request):
    """§3.3 autosave (every 20s + on blur) posts in the background via
    fetch(); it must never navigate the page away from under the preparer,
    so these requests get a small JSON response instead of a redirect."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _ajax_saved_response(tax_return):
    return JsonResponse({
        'saved': True,
        'version': tax_return.version,
        'savedAt': tax_return.updated_at.strftime('%H:%M:%S'),
    })


def _check_version_conflict(request, tax_return):
    """§3.3 optimistic locking: the form carries the draft version it was
    loaded against (`_version`, stamped from `draft_version` in the chrome
    context); if the stored version has moved on since, someone else's edit
    would otherwise be silently overwritten. Returns a conflict message, or
    None if it's safe to proceed."""
    submitted = request.POST.get('_version')
    if submitted is None or str(tax_return.version) == submitted:
        return None
    last = tax_return.audit_log.exclude(kind=AuditLogEntry.KIND_VALIDATION_RUN).first()
    who = last.actor.username if last and last.actor else 'someone'
    when = last.at.strftime('%H:%M') if last else 'a moment ago'
    return f'This return was edited by {who} at {when} since you opened it. Reload the page to see the latest version before continuing.'


def _diff_model(old, new, path=''):
    """Recursively diff two ReturnModel dict trees, yielding (path, old, new)
    for every leaf that changed. Lists are compared element-by-element when
    their lengths match (so a single row edit reports as one leaf change per
    field), and as a single whole-list change otherwise (a row added/removed)
    -- diffing an insert/delete field-by-field would misattribute every row
    after the edit point."""
    changes = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in set(old.keys()) | set(new.keys()):
            changes.extend(_diff_model(old.get(key), new.get(key), f'{path}.{key}' if path else key))
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for i, (o, n) in enumerate(zip(old, new)):
            changes.extend(_diff_model(o, n, f'{path}[{i}]'))
    elif old != new:
        changes.append((path, old, new))
    return changes


def _log_field_changes(tax_return, before, after, actor):
    """Architecture mandate 6: every field change is audited (who, when, old
    value, new value). `before`/`after` are ReturnModel dict snapshots taken
    around a single screen's save."""
    entries = [
        AuditLogEntry(
            tax_return=tax_return, actor=actor, kind=AuditLogEntry.KIND_FIELD_CHANGE,
            field_path=path, old_value=old_value, new_value=new_value,
        )
        for path, old_value, new_value in _diff_model(before, after)
    ]
    if entries:
        AuditLogEntry.objects.bulk_create(entries)


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


def _personal_info_initial(model):
    pi = model['personalInfo']
    addr = pi['primaryAddress']
    return {
        'first_name': pi['firstName'],
        'middle_name': pi['middleName'],
        'last_name': pi['lastName'],
        'pan': pi['pan'],
        'dob': pi['dob'] or None,
        'aadhaar': pi['aadhaar'],
        'employer_category': pi['employerCategory'],
        'primary_mobile': pi['contact']['primaryMobile'],
        'secondary_mobile': pi['contact']['secondaryMobile'],
        'primary_email': pi['contact']['primaryEmail'],
        'secondary_email': pi['contact']['secondaryEmail'],
        'flat_door_building': addr['flatDoorBuilding'],
        'premise_building_name': addr['premiseBuildingName'],
        'road_street': addr['roadStreet'],
        'area_locality': addr['areaLocality'],
        'town_city_district': addr['townCityDistrict'],
        'state_code': addr['stateCode'],
        'pin_code': addr['pinCode'],
        'secondary_address_same_as_primary': pi['secondaryAddressSameAsPrimary'] or 'Y',
        'return_file_sec': model['filingStatus']['returnFileSec'],
        'opt_out_of_new_regime': model['filingStatus']['optOutOfNewRegime'] or 'N',
        'orig_return_ack_no': model['filingStatus']['origReturnAckNo'],
        'orig_return_filed_date': model['filingStatus']['origReturnFiledDate'] or None,
        'orig_return_file_sec': model['filingStatus']['origReturnFileSec'],
        'a23_responses_original': model['filingStatus']['a23ResponsesOriginal'],
        'a23_responses_current': model['filingStatus']['a23ResponsesCurrent'],
        'seventh_proviso_139': model['filingStatus']['seventhProviso139'] or 'N',
        'travel_expense_above_2lakh': model['filingStatus']['seventhProviso']['travelExpenseAbove2Lakh'] or 'N',
        'travel_expense_amount': model['filingStatus']['seventhProviso']['travelExpenseAmount'],
        'electricity_above_1lakh': model['filingStatus']['seventhProviso']['electricityAbove1Lakh'] or 'N',
        'electricity_amount': model['filingStatus']['seventhProviso']['electricityAmount'],
        'clause_iv_applies': model['filingStatus']['seventhProviso']['clauseIvApplies'] or 'N',
        'representative_assessee_flag': model['filingStatus']['representativeAssesseeFlag'] or 'N',
        'representative_name': (model['filingStatus']['representativeAssessee'] or {}).get('name', ''),
        'representative_email': (model['filingStatus']['representativeAssessee'] or {}).get('email', ''),
        'representative_mobile': (model['filingStatus']['representativeAssessee'] or {}).get('mobile', ''),
        'representative_pan': (model['filingStatus']['representativeAssessee'] or {}).get('pan', ''),
        'representative_capacity_other': (model['filingStatus']['representativeAssessee'] or {}).get('capacityOther', ''),
        'verification_capacity': model['verification']['capacity'] or 'S',
    }


def _apply_personal_info_form(model, cleaned):
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
    fs['returnFileSec'] = cleaned['return_file_sec']
    fs['optOutOfNewRegime'] = cleaned['opt_out_of_new_regime']
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


def _bank_accounts_initial(model):
    return [
        {
            'ifsc': b['ifsc'],
            'bank_name': b['bankName'],
            'account_number': b['accountNumber'],
            'account_type': b['accountType'],
            'nominate_for_refund': b['nominateForRefund'],
        }
        for b in model.get('bankAccounts', [])
    ]


def _verify_ifsc_if_present(ifsc):
    """A-107 verification for a single optional IFSC field (Schedule 80G /
    80GGC rows carry an IFSC only for non-cash donations). Returns
    (verified: bool|None, note: str) -- None means "not applicable"."""
    if not ifsc:
        return None, ''
    lookup = ifsc_validator.validate(ifsc)
    return lookup.status == 'VALID', lookup.note


def _apply_bank_formset(model, formset):
    accounts = []
    for i, form in enumerate(formset):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        cleaned = form.cleaned_data
        if not cleaned.get('ifsc'):
            continue
        existing = model.get('bankAccounts', [])
        prior = existing[i] if i < len(existing) else {}
        ifsc = cleaned['ifsc'].strip().upper()

        # A-107: verify against the (stub) RBI/GIFT directory on every save so
        # a changed IFSC is re-checked; fails closed per itr1.services.ifsc.
        bank_name = cleaned.get('bank_name') or prior.get('bankName', '')
        if ifsc == prior.get('ifsc') and prior.get('ifscVerified') is not None:
            verified, note = prior.get('ifscVerified', False), prior.get('ifscVerificationNote', '')
        else:
            lookup = ifsc_validator.validate(ifsc)
            verified, note = lookup.status == 'VALID', lookup.note
            # §4.6: "Bank Name (auto-populated from IFSC)" -- once verified,
            # the directory's name wins over free-text entry.
            if verified and lookup.record:
                bank_name = lookup.record.bank

        accounts.append({
            'id': prior.get('id') or f'bank-{i + 1}',
            'ifsc': ifsc,
            'bankName': bank_name,
            'accountNumber': cleaned['account_number'],
            'accountType': cleaned['account_type'],
            'nominateForRefund': cleaned['nominate_for_refund'],
            'ifscVerified': verified,
            'ifscVerificationNote': note,
        })
    model['bankAccounts'] = accounts


def personal_info(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    bank_errors = []
    conflict_message = None
    report = None

    if request.method == 'POST':
        form = PersonalInfoForm(request.POST)
        formset = BankAccountFormSet(request.POST, prefix='bank')
        conflict_message = _check_version_conflict(request, tax_return)
        if conflict_message:
            if _is_ajax(request):
                return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
        elif form.is_valid() and formset.is_valid():
            before = copy.deepcopy(model)
            _apply_personal_info_form(model, form.cleaned_data)
            _apply_bank_formset(model, formset)
            _log_field_changes(tax_return, before, model, request.user if request.user.is_authenticated else None)
            tax_return.bump_version()

            action = request.POST.get('action', 'save')
            if action == 'confirm':
                report = validate(model, tier=2, screen='PERSONAL_INFO')
                # §4.6: at least one bank account, exactly one nominated -- a
                # screen-level product constraint, not a numbered CBDT rule,
                # so it's checked alongside (not inside) the rule registry.
                bank_errors = bank_accounts_structural_errors(model.get('bankAccounts', []))
                if report.errors or bank_errors:
                    _set_screen_status(tax_return, 'PERSONAL_INFO', 'HAS_ERRORS')
                else:
                    _set_screen_status(tax_return, 'PERSONAL_INFO', 'CONFIRMED')
                tax_return.save()
                AuditLogEntry.objects.create(
                    tax_return=tax_return, actor=request.user if request.user.is_authenticated else None,
                    kind=AuditLogEntry.KIND_VALIDATION_RUN,
                    payload={'screen': 'PERSONAL_INFO', 'errors': [e.ruleId for e in report.errors], 'bankErrors': bank_errors},
                )
                if not report.errors and not bank_errors:
                    return redirect('itr1:gross_total_income', return_id=return_id)
            else:
                _set_screen_status(tax_return, 'PERSONAL_INFO', 'IN_PROGRESS')
                tax_return.save()
                if _is_ajax(request):
                    return _ajax_saved_response(tax_return)
                return redirect('itr1:personal_info', return_id=return_id)
    else:
        form = PersonalInfoForm(initial=_personal_info_initial(model))
        formset = BankAccountFormSet(initial=_bank_accounts_initial(model), prefix='bank')

    return render(request, 'itr1/personal_info.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Personal Information',
        'form': form,
        'formset': formset,
        'return_id': return_id,
        'bank_errors': bank_errors,
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return),
    })


def _screen_view(request, return_id, screen_id, label, template='itr1/screen_placeholder.html', extra=None):
    tax_return = _get_return(request, return_id)
    context = {
        'ay': tax_return.data['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': label,
        'screen_id': screen_id,
        'return_id': return_id,
        'tax_return': tax_return,
        **_chrome_context(tax_return),
    }
    if extra:
        context.update(extra(tax_return))
    return render(request, template, context)


def _gti_initial(model):
    inc = model['income']
    salary = {
        'salary17_1': inc['salary17_1'],
        'perquisites17_2': inc['perquisites17_2'],
        'profits_in_lieu17_3': inc['profitsInLieu17_3'],
        'entertainment_allowance_16ii': inc['entertainmentAllowance16ii'],
        'professional_tax_16iii': inc['professionalTax16iii'],
    }
    exempt_allowances = [
        {'nature': r['nature'], 'amount': r['amount']}
        for r in inc.get('exemptAllowances', [])
    ]
    properties = [
        {
            'property_type': p['propertyType'],
            'co_owned': p['coOwned'],
            'assessee_share_percent': p['assesseeSharePercent'],
            'gross_rent': p['grossRent'],
            'local_taxes': p['localTaxes'],
            'rent_not_realized': p['rentNotRealized'],
            'interest_on_borrowed_capital': p['interestOnBorrowedCapital'],
        }
        for p in inc.get('properties', [])
    ]
    other_sources = [
        {'nature': r['nature'], 'amount': r['amount']}
        for r in inc.get('otherSources', [])
    ]
    exempt_income = [
        {
            'category': r['category'],
            'sub_category': r['subCategory'],
            'description': r['description'],
            'amount': r['amount'],
        }
        for r in inc.get('exemptIncome', [])
    ]
    return salary, exempt_allowances, properties, other_sources, exempt_income


def _apply_gti_forms(model, salary_cleaned, allowance_formset, property_formset, other_source_formset, exempt_income_formset):
    inc = model['income']

    inc['salary17_1'] = salary_cleaned['salary17_1']
    inc['perquisites17_2'] = salary_cleaned['perquisites17_2']
    inc['profitsInLieu17_3'] = salary_cleaned['profits_in_lieu17_3']
    inc['entertainmentAllowance16ii'] = salary_cleaned['entertainment_allowance_16ii'] or 0
    inc['professionalTax16iii'] = salary_cleaned['professional_tax_16iii'] or 0

    existing_allowances = inc.get('exemptAllowances', [])
    allowances = []
    for i, form in enumerate(allowance_formset):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        cleaned = form.cleaned_data
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
    for i, form in enumerate(property_formset):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        cleaned = form.cleaned_data
        if not cleaned.get('property_type'):
            continue
        prior = existing_properties[i] if i < len(existing_properties) else {}
        properties.append({
            'id': prior.get('id') or f'hp-{i + 1}',
            'address': prior.get('address') or blank_address(),
            'propertyOwner': prior.get('propertyOwner', ''),
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
    for i, form in enumerate(other_source_formset):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        cleaned = form.cleaned_data
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
    for i, form in enumerate(exempt_income_formset):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        cleaned = form.cleaned_data
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


def gross_total_income(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None

    if request.method == 'POST':
        salary_form = SalaryForm(request.POST)
        allowance_formset = ExemptAllowanceFormSet(request.POST, prefix='allow')
        property_formset = HousePropertyFormSet(request.POST, prefix='hp')
        other_source_formset = OtherSourceFormSet(request.POST, prefix='os')
        exempt_income_formset = ExemptIncomeFormSet(request.POST, prefix='ei')

        forms_valid = (
            salary_form.is_valid()
            and allowance_formset.is_valid()
            and property_formset.is_valid()
            and other_source_formset.is_valid()
            and exempt_income_formset.is_valid()
        )
        conflict_message = _check_version_conflict(request, tax_return)
        if conflict_message:
            if _is_ajax(request):
                return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
        elif forms_valid:
            before = copy.deepcopy(model)
            _apply_gti_forms(
                model, salary_form.cleaned_data, allowance_formset,
                property_formset, other_source_formset, exempt_income_formset,
            )
            _log_field_changes(tax_return, before, model, request.user if request.user.is_authenticated else None)
            tax_return.bump_version()

            action = request.POST.get('action', 'save')
            if action == 'confirm':
                report = validate(model, tier=2, screen='GROSS_TOTAL_INCOME')
                if report.errors:
                    _set_screen_status(tax_return, 'GROSS_TOTAL_INCOME', 'HAS_ERRORS')
                else:
                    _set_screen_status(tax_return, 'GROSS_TOTAL_INCOME', 'CONFIRMED')
                tax_return.save()
                AuditLogEntry.objects.create(
                    tax_return=tax_return, actor=request.user if request.user.is_authenticated else None,
                    kind=AuditLogEntry.KIND_VALIDATION_RUN,
                    payload={'screen': 'GROSS_TOTAL_INCOME', 'errors': [e.ruleId for e in report.errors]},
                )
                if not report.errors:
                    return redirect('itr1:total_deductions', return_id=return_id)
            else:
                _set_screen_status(tax_return, 'GROSS_TOTAL_INCOME', 'IN_PROGRESS')
                tax_return.save()
                if _is_ajax(request):
                    return _ajax_saved_response(tax_return)
                return redirect('itr1:gross_total_income', return_id=return_id)
    else:
        salary_initial, allowances_initial, properties_initial, other_sources_initial, exempt_income_initial = _gti_initial(model)
        salary_form = SalaryForm(initial=salary_initial)
        allowance_formset = ExemptAllowanceFormSet(initial=allowances_initial, prefix='allow')
        property_formset = HousePropertyFormSet(initial=properties_initial, prefix='hp')
        other_source_formset = OtherSourceFormSet(initial=other_sources_initial, prefix='os')
        exempt_income_formset = ExemptIncomeFormSet(initial=exempt_income_initial, prefix='ei')

    computed = compute(model)

    return render(request, 'itr1/gross_total_income.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Gross Total Income',
        'salary_form': salary_form,
        'allowance_formset': allowance_formset,
        'property_formset': property_formset,
        'other_source_formset': other_source_formset,
        'exempt_income_formset': exempt_income_formset,
        'return_id': return_id,
        'computed': computed,
        'gti_display': format_indian(computed['grossTotalIncome']),
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return, computed),
    })


def _deductions_initial(model):
    d = model['deductions']

    deductions_initial = {
        's80CCD1': d['s80CCD1'],
        'pran_numbers': ', '.join(x for x in d.get('pranNumbers', []) if x),
        's80CCD1B': d['s80CCD1B'],
        's80CCD2': d['s80CCD2'],
        's80CCH': d['s80CCH'],
        's80D': d['s80D'],
        's80G': d['s80G'],
        's80DDB': d['s80DDB'],
        's80DDBUsrType': d['s80DDBUsrType'],
        's80DDBDisease': d['s80DDBDisease'],
        'stampDutyValue80EEA': d['stampDutyValue80EEA'],
        's80GG': d['s80GG'],
        'form10BAFiled': d['form10BAFiled'],
        'form10BAAckNo': d['form10BAAckNo'],
        's80GGA': d['s80GGA'],
        's80GGC': d['s80GGC'],
        's80TTA': d['s80TTA'],
        's80TTB': d['s80TTB'],
    }

    sched80c_initial = [
        {'identification_no': r.get('identificationNo', ''), 'amount': r['amount']}
        for r in d.get('schedule80C', [])
    ]
    sched80ccc_initial = [
        {'name_of_identifier': r.get('nameOfIdentifier', ''), 'amount': r['amount']}
        for r in d.get('pensionContribution80CCC', [])
    ]

    d80 = d['schedule80D']
    sched80d_initial = {
        'self_family_senior_flag': d80['selfFamilySeniorFlag'],
        'self_family_health_insurance_premium': d80['selfFamily']['healthInsurancePremium'],
        'self_family_preventive_health_checkup': d80['selfFamily']['preventiveHealthCheckup'],
        'self_family_medical_expenditure': d80['selfFamily']['medicalExpenditure'],
        'self_family_senior_health_insurance_premium': d80['selfFamilySenior']['healthInsurancePremium'],
        'self_family_senior_preventive_health_checkup': d80['selfFamilySenior']['preventiveHealthCheckup'],
        'self_family_senior_medical_expenditure': d80['selfFamilySenior']['medicalExpenditure'],
        'parents_senior_flag': d80['parentsSeniorFlag'],
        'parents_health_insurance_premium': d80['parents']['healthInsurancePremium'],
        'parents_preventive_health_checkup': d80['parents']['preventiveHealthCheckup'],
        'parents_medical_expenditure': d80['parents']['medicalExpenditure'],
        'parents_senior_health_insurance_premium': d80['parentsSenior']['healthInsurancePremium'],
        'parents_senior_preventive_health_checkup': d80['parentsSenior']['preventiveHealthCheckup'],
        'parents_senior_medical_expenditure': d80['parentsSenior']['medicalExpenditure'],
    }

    def disability_initial(sched):
        return {
            'nature_of_disability': sched['natureOfDisability'],
            'type_of_disability': sched['typeOfDisability'],
            'amount': sched['amount'],
            'form10IAFiled': sched['form10IAFiled'],
            'form10IAAckNo': sched['form10IAAckNo'],
        }

    def loan_rows_initial(rows):
        return [
            {
                'lender_name': r.get('lenderName', ''),
                'loan_account_no': r.get('loanAccountNo', ''),
                'date_of_loan': r.get('dateOfLoan') or None,
                'interest': r['interest'],
            }
            for r in rows
        ]

    sched80g = d['schedule80G']
    sched80g_initial = []
    for block_letter, model_key in SCHEDULE_80G_BLOCK_MODEL_KEY.items():
        for r in sched80g.get(model_key, []):
            sched80g_initial.append({
                'block': block_letter,
                'donee_name': r.get('name', ''),
                'pan': r.get('pan', ''),
                'donation_cash': r['donationCash'],
                'donation_other_mode': r['donationOtherMode'],
                'ifsc': r.get('ifsc', ''),
                'transaction_ref_no': r.get('transactionRefNo', ''),
            })

    sched80gga_initial = [
        {
            'donee_name': r.get('name', ''),
            'pan': r.get('pan', ''),
            'donation_cash': r['donationCash'],
            'donation_other_mode': r['donationOtherMode'],
        }
        for r in d.get('schedule80GGA', [])
    ]
    sched80ggc_initial = [
        {
            'donation_date': r.get('donationDate') or None,
            'political_party_name': r.get('politicalPartyName', ''),
            'political_party_pan': r.get('politicalPartyPan', ''),
            'donation_cash': r['donationCash'],
            'donation_other_mode': r['donationOtherMode'],
            'ifsc': r.get('ifsc', ''),
            'transaction_ref_no': r.get('transactionRefNo', ''),
        }
        for r in d.get('schedule80GGC', [])
    ]

    return {
        'deductions': deductions_initial,
        'sched80c': sched80c_initial,
        'sched80ccc': sched80ccc_initial,
        'sched80d': sched80d_initial,
        'disability_80dd': disability_initial(d['schedule80DD']),
        'disability_80u': disability_initial(d['schedule80U']),
        'sched80e': loan_rows_initial(d.get('schedule80E', [])),
        'sched80ee': loan_rows_initial(d.get('schedule80EE', [])),
        'sched80eea': loan_rows_initial(d.get('schedule80EEA', [])),
        'sched80eeb': loan_rows_initial(d.get('schedule80EEB', [])),
        'sched80g': sched80g_initial,
        'sched80gga': sched80gga_initial,
        'sched80ggc': sched80ggc_initial,
    }


def _apply_deductions_forms(model, cleaned, sched80c_fs, sched80ccc_fs, sched80d_cleaned,
                             disability_80dd_cleaned, disability_80u_cleaned,
                             sched80e_fs, sched80ee_fs, sched80eea_fs, sched80eeb_fs,
                             sched80g_fs, sched80gga_fs, sched80ggc_fs):
    d = model['deductions']

    # --- Schedule 80C / 80CCC: s80C and s80CCC are derived (not user fields)
    # because tier-2 rules A-241/A-301-339 require an exact match to the
    # schedule total.
    existing = d.get('schedule80C', [])
    rows = []
    for i, form in enumerate(sched80c_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        row_cleaned = form.cleaned_data
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
    d['s80C'] = sum(r['amount'] for r in rows)

    existing = d.get('pensionContribution80CCC', [])
    rows = []
    for i, form in enumerate(sched80ccc_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        row_cleaned = form.cleaned_data
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
    d['s80CCC'] = sum(r['amount'] for r in rows)

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
    d['s80DD'] = d['schedule80DD']['amount']
    d['schedule80U'] = apply_disability(disability_80u_cleaned, d['schedule80U'])
    d['s80U'] = d['schedule80U']['amount']

    d['s80DDB'] = cleaned.get('s80DDB') or 0
    d['s80DDBUsrType'] = cleaned.get('s80DDBUsrType') or ''
    d['s80DDBDisease'] = cleaned.get('s80DDBDisease') or ''

    # --- Loan-interest schedules (80E / 80EE / 80EEA / 80EEB): s80E/s80EE/
    # s80EEA/s80EEB are derived from the schedule total for the same reason
    # as 80C/80CCC above.
    def apply_loan_formset(formset, existing_rows, prefix):
        loan_rows = []
        for i, form in enumerate(formset):
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            row_cleaned = form.cleaned_data
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

    d['schedule80E'] = apply_loan_formset(sched80e_fs, d.get('schedule80E', []), '80e')
    d['s80E'] = sum(r['interest'] for r in d['schedule80E'])
    d['schedule80EE'] = apply_loan_formset(sched80ee_fs, d.get('schedule80EE', []), '80ee')
    d['s80EE'] = sum(r['interest'] for r in d['schedule80EE'])
    d['schedule80EEA'] = apply_loan_formset(sched80eea_fs, d.get('schedule80EEA', []), '80eea')
    d['s80EEA'] = sum(r['interest'] for r in d['schedule80EEA'])
    d['schedule80EEB'] = apply_loan_formset(sched80eeb_fs, d.get('schedule80EEB', []), '80eeb')
    d['s80EEB'] = sum(r['interest'] for r in d['schedule80EEB'])
    d['stampDutyValue80EEA'] = cleaned.get('stampDutyValue80EEA') or 0

    # --- 80G: one combined formset with a block selector standing in for the
    # 4 separate CBDT tables (Don100Percent / Don50PercentNoApprReqd / ...).
    new_sched80g = {model_key: [] for model_key in SCHEDULE_80G_BLOCK_MODEL_KEY.values()}
    for i, form in enumerate(sched80g_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        row_cleaned = form.cleaned_data
        if not any([
            row_cleaned.get('donee_name'), row_cleaned.get('pan'),
            row_cleaned.get('donation_cash'), row_cleaned.get('donation_other_mode'),
        ]):
            continue
        block = row_cleaned.get('block') or 'A'
        model_key = SCHEDULE_80G_BLOCK_MODEL_KEY.get(block, 'don100Percent')
        ifsc = (row_cleaned.get('ifsc') or '').strip().upper()
        # A-107 also covers Schedule 80G IFSCs (non-cash donations).
        ifsc_verified, ifsc_note = _verify_ifsc_if_present(ifsc)
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
            'ifscVerified': ifsc_verified,
            'ifscVerificationNote': ifsc_note,
        })
    d['schedule80G'] = new_sched80g
    d['s80G'] = cleaned.get('s80G') or 0

    existing = d.get('schedule80GGA', [])
    rows = []
    for i, form in enumerate(sched80gga_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        row_cleaned = form.cleaned_data
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
    for i, form in enumerate(sched80ggc_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        row_cleaned = form.cleaned_data
        if not any([row_cleaned.get('political_party_name'), row_cleaned.get('donation_cash'), row_cleaned.get('donation_other_mode')]):
            continue
        prior = existing[i] if i < len(existing) else {}
        ifsc = (row_cleaned.get('ifsc') or '').strip().upper()
        # A-107 also covers Schedule 80GGC IFSCs (non-cash donations).
        if ifsc == prior.get('ifsc') and prior.get('ifscVerified') is not None:
            ifsc_verified, ifsc_note = prior.get('ifscVerified'), prior.get('ifscVerificationNote', '')
        else:
            ifsc_verified, ifsc_note = _verify_ifsc_if_present(ifsc)
        rows.append({
            'id': prior.get('id') or f'ggc-{i + 1}',
            'donationDate': row_cleaned['donation_date'].isoformat() if row_cleaned.get('donation_date') else '',
            'politicalPartyName': row_cleaned.get('political_party_name') or '',
            'politicalPartyPan': (row_cleaned.get('political_party_pan') or '').upper(),
            'donationCash': row_cleaned.get('donation_cash') or 0,
            'donationOtherMode': row_cleaned.get('donation_other_mode') or 0,
            'transactionRefNo': row_cleaned.get('transaction_ref_no') or '',
            'ifsc': ifsc,
            'ifscVerified': ifsc_verified,
            'ifscVerificationNote': ifsc_note,
        })
    d['schedule80GGC'] = rows
    d['s80GGC'] = cleaned.get('s80GGC') or 0

    d['s80GG'] = cleaned.get('s80GG') or 0
    d['form10BAFiled'] = cleaned.get('form10BAFiled') or False
    d['form10BAAckNo'] = cleaned.get('form10BAAckNo') or ''

    d['s80TTA'] = cleaned.get('s80TTA') or 0
    d['s80TTB'] = cleaned.get('s80TTB') or 0


def total_deductions(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None

    if request.method == 'POST':
        deductions_form = DeductionsForm(request.POST)
        sched80c_fs = Schedule80CFormSet(request.POST, prefix='s80c')
        sched80ccc_fs = Schedule80CCCFormSet(request.POST, prefix='s80ccc')
        sched80d_form = Schedule80DForm(request.POST)
        disability_80dd_form = Disability80DDUForm(request.POST, prefix='dd')
        disability_80u_form = Disability80DDUForm(request.POST, prefix='u')
        sched80e_fs = Schedule80EFormSet(request.POST, prefix='s80e')
        sched80ee_fs = Schedule80EEFormSet(request.POST, prefix='s80ee')
        sched80eea_fs = Schedule80EEAFormSet(request.POST, prefix='s80eea')
        sched80eeb_fs = Schedule80EEBFormSet(request.POST, prefix='s80eeb')
        sched80g_fs = Schedule80GFormSet(request.POST, prefix='s80g')
        sched80gga_fs = Schedule80GGAFormSet(request.POST, prefix='s80gga')
        sched80ggc_fs = Schedule80GGCFormSet(request.POST, prefix='s80ggc')

        forms_valid = (
            deductions_form.is_valid()
            and sched80c_fs.is_valid()
            and sched80ccc_fs.is_valid()
            and sched80d_form.is_valid()
            and disability_80dd_form.is_valid()
            and disability_80u_form.is_valid()
            and sched80e_fs.is_valid()
            and sched80ee_fs.is_valid()
            and sched80eea_fs.is_valid()
            and sched80eeb_fs.is_valid()
            and sched80g_fs.is_valid()
            and sched80gga_fs.is_valid()
            and sched80ggc_fs.is_valid()
        )
        conflict_message = _check_version_conflict(request, tax_return)
        if conflict_message:
            if _is_ajax(request):
                return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
        elif forms_valid:
            before = copy.deepcopy(model)
            _apply_deductions_forms(
                model, deductions_form.cleaned_data, sched80c_fs, sched80ccc_fs, sched80d_form.cleaned_data,
                disability_80dd_form.cleaned_data, disability_80u_form.cleaned_data,
                sched80e_fs, sched80ee_fs, sched80eea_fs, sched80eeb_fs,
                sched80g_fs, sched80gga_fs, sched80ggc_fs,
            )
            _log_field_changes(tax_return, before, model, request.user if request.user.is_authenticated else None)
            tax_return.bump_version()

            action = request.POST.get('action', 'save')
            if action == 'confirm':
                report = validate(model, tier=2, screen='TOTAL_DEDUCTIONS')
                if report.errors:
                    _set_screen_status(tax_return, 'TOTAL_DEDUCTIONS', 'HAS_ERRORS')
                else:
                    _set_screen_status(tax_return, 'TOTAL_DEDUCTIONS', 'CONFIRMED')
                tax_return.save()
                AuditLogEntry.objects.create(
                    tax_return=tax_return, actor=request.user if request.user.is_authenticated else None,
                    kind=AuditLogEntry.KIND_VALIDATION_RUN,
                    payload={'screen': 'TOTAL_DEDUCTIONS', 'errors': [e.ruleId for e in report.errors]},
                )
                if not report.errors:
                    return redirect('itr1:tax_paid', return_id=return_id)
            else:
                _set_screen_status(tax_return, 'TOTAL_DEDUCTIONS', 'IN_PROGRESS')
                tax_return.save()
                if _is_ajax(request):
                    return _ajax_saved_response(tax_return)
                return redirect('itr1:total_deductions', return_id=return_id)
    else:
        initial = _deductions_initial(model)
        deductions_form = DeductionsForm(initial=initial['deductions'])
        sched80c_fs = Schedule80CFormSet(initial=initial['sched80c'], prefix='s80c')
        sched80ccc_fs = Schedule80CCCFormSet(initial=initial['sched80ccc'], prefix='s80ccc')
        sched80d_form = Schedule80DForm(initial=initial['sched80d'])
        disability_80dd_form = Disability80DDUForm(initial=initial['disability_80dd'], prefix='dd')
        disability_80u_form = Disability80DDUForm(initial=initial['disability_80u'], prefix='u')
        sched80e_fs = Schedule80EFormSet(initial=initial['sched80e'], prefix='s80e')
        sched80ee_fs = Schedule80EEFormSet(initial=initial['sched80ee'], prefix='s80ee')
        sched80eea_fs = Schedule80EEAFormSet(initial=initial['sched80eea'], prefix='s80eea')
        sched80eeb_fs = Schedule80EEBFormSet(initial=initial['sched80eeb'], prefix='s80eeb')
        sched80g_fs = Schedule80GFormSet(initial=initial['sched80g'], prefix='s80g')
        sched80gga_fs = Schedule80GGAFormSet(initial=initial['sched80gga'], prefix='s80gga')
        sched80ggc_fs = Schedule80GGCFormSet(initial=initial['sched80ggc'], prefix='s80ggc')

    computed = compute(model)

    return render(request, 'itr1/total_deductions.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Total Deductions',
        'deductions_form': deductions_form,
        'sched80c_formset': sched80c_fs,
        'sched80ccc_formset': sched80ccc_fs,
        'sched80d_form': sched80d_form,
        'disability_80dd_form': disability_80dd_form,
        'disability_80u_form': disability_80u_form,
        'sched80e_formset': sched80e_fs,
        'sched80ee_formset': sched80ee_fs,
        'sched80eea_formset': sched80eea_fs,
        'sched80eeb_formset': sched80eeb_fs,
        'sched80g_formset': sched80g_fs,
        'sched80gga_formset': sched80gga_fs,
        'sched80ggc_formset': sched80ggc_fs,
        'return_id': return_id,
        'computed': computed,
        'total_deductions_display': format_indian(computed['totalDeductions']),
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return, computed),
    })


def _tax_paid_initial(model):
    tp = model['taxPaid']

    tds1_initial = [
        {
            'tan': r.get('tan', ''),
            'deductor_name': r.get('deductorName', ''),
            'income_chargeable_salary': r['incomeChargeableSalary'],
            'total_tax_deducted': r['totalTaxDeducted'],
        }
        for r in tp.get('tds1', [])
    ]
    tds2_initial = [
        {
            'tan_or_pan': r.get('tanOrPan', ''),
            'deductor_name': r.get('deductorName', ''),
            'gross_receipt': r['grossReceipt'],
            'deducted_year': r.get('deductedYear', ''),
            'tax_deducted': r['taxDeducted'],
            'tds_claimed_this_year': r['tdsClaimedThisYear'],
            'tds_section': r.get('tdsSection', ''),
            'head_of_income': r.get('headOfIncome', ''),
        }
        for r in tp.get('tds2', [])
    ]
    tds3_initial = [
        {
            'pan_of_tenant': r.get('panOfTenant', ''),
            'aadhaar_of_tenant': r.get('aadhaarOfTenant', ''),
            'name_of_tenant': r.get('nameOfTenant', ''),
            'gross_receipt': r['grossReceipt'],
            'deducted_year': r.get('deductedYear', ''),
            'tax_deducted': r['taxDeducted'],
            'tds_claimed_this_year': r['tdsClaimedThisYear'],
            'tds_section': r.get('tdsSection', ''),
            'head_of_income': r.get('headOfIncome', ''),
        }
        for r in tp.get('tds3', [])
    ]
    tcs_initial = [
        {
            'tan': r.get('tan', ''),
            'collector_name': r.get('collectorName', ''),
            'tax_collected': r['taxCollected'],
            'collected_year': r.get('collectedYear', ''),
            'tcs_claimed_this_year': r['tcsClaimedThisYear'],
        }
        for r in tp.get('tcs', [])
    ]
    challans_initial = [
        {
            'bsr_code': r.get('bsrCode', ''),
            'date_of_deposit': r['dateOfDeposit'] or None,
            'challan_serial_no': r.get('challanSerialNo', ''),
            'amount': r['amount'],
        }
        for r in tp.get('challans', [])
    ]

    return {
        'tds1': tds1_initial,
        'tds2': tds2_initial,
        'tds3': tds3_initial,
        'tcs': tcs_initial,
        'challans': challans_initial,
    }


def _apply_tax_paid_forms(model, tds1_fs, tds2_fs, tds3_fs, tcs_fs, challan_fs):
    tp = model['taxPaid']

    existing = tp.get('tds1', [])
    rows = []
    for i, form in enumerate(tds1_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        c = form.cleaned_data
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
    for i, form in enumerate(tds2_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        c = form.cleaned_data
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
    for i, form in enumerate(tds3_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        c = form.cleaned_data
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
    for i, form in enumerate(tcs_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        c = form.cleaned_data
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
    for i, form in enumerate(challan_fs):
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        c = form.cleaned_data
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


def tax_paid(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None

    if request.method == 'POST':
        tds1_fs = Tds1FormSet(request.POST, prefix='tds1')
        tds2_fs = Tds2FormSet(request.POST, prefix='tds2')
        tds3_fs = Tds3FormSet(request.POST, prefix='tds3')
        tcs_fs = TcsFormSet(request.POST, prefix='tcs')
        challan_fs = ChallanFormSet(request.POST, prefix='challan')

        forms_valid = (
            tds1_fs.is_valid()
            and tds2_fs.is_valid()
            and tds3_fs.is_valid()
            and tcs_fs.is_valid()
            and challan_fs.is_valid()
        )
        conflict_message = _check_version_conflict(request, tax_return)
        if conflict_message:
            if _is_ajax(request):
                return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
        elif forms_valid:
            before = copy.deepcopy(model)
            _apply_tax_paid_forms(model, tds1_fs, tds2_fs, tds3_fs, tcs_fs, challan_fs)
            _log_field_changes(tax_return, before, model, request.user if request.user.is_authenticated else None)
            tax_return.bump_version()

            action = request.POST.get('action', 'save')
            if action == 'confirm':
                report = validate(model, tier=2, screen='TAX_PAID')
                if report.errors:
                    _set_screen_status(tax_return, 'TAX_PAID', 'HAS_ERRORS')
                else:
                    _set_screen_status(tax_return, 'TAX_PAID', 'CONFIRMED')
                tax_return.save()
                AuditLogEntry.objects.create(
                    tax_return=tax_return, actor=request.user if request.user.is_authenticated else None,
                    kind=AuditLogEntry.KIND_VALIDATION_RUN,
                    payload={'screen': 'TAX_PAID', 'errors': [e.ruleId for e in report.errors]},
                )
                if not report.errors:
                    return redirect('itr1:tax_liability', return_id=return_id)
            else:
                _set_screen_status(tax_return, 'TAX_PAID', 'IN_PROGRESS')
                tax_return.save()
                if _is_ajax(request):
                    return _ajax_saved_response(tax_return)
                return redirect('itr1:tax_paid', return_id=return_id)
    else:
        initial = _tax_paid_initial(model)
        tds1_fs = Tds1FormSet(initial=initial['tds1'], prefix='tds1')
        tds2_fs = Tds2FormSet(initial=initial['tds2'], prefix='tds2')
        tds3_fs = Tds3FormSet(initial=initial['tds3'], prefix='tds3')
        tcs_fs = TcsFormSet(initial=initial['tcs'], prefix='tcs')
        challan_fs = ChallanFormSet(initial=initial['challans'], prefix='challan')

    computed = compute(model)

    return render(request, 'itr1/tax_paid.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Tax Paid',
        'tds1_formset': tds1_fs,
        'tds2_formset': tds2_fs,
        'tds3_formset': tds3_fs,
        'tcs_formset': tcs_fs,
        'challan_formset': challan_fs,
        'return_id': return_id,
        'computed': computed,
        'total_taxes_paid_display': format_indian(computed['taxesPaid']['total']),
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return, computed),
    })


def _tax_liability_initial(model):
    tl = model['taxLiability']
    return {
        'relief89': tl['relief89'],
        'form10EFiled': tl['form10EFiled'],
        'form10EAckNo': tl['form10EAckNo'],
        'interest234AOverride': tl.get('interest234AOverride'),
        'interest234BOverride': tl.get('interest234BOverride'),
        'fee234FOverride': tl.get('fee234FOverride'),
    }


def _apply_tax_liability_form(model, cleaned):
    tl = model['taxLiability']
    tl['relief89'] = cleaned.get('relief89') or 0
    tl['form10EFiled'] = cleaned.get('form10EFiled') or False
    tl['form10EAckNo'] = cleaned.get('form10EAckNo') or ''
    # Left blank -> None, meaning "use the engine's computed default" (see
    # forms.py's TaxLiabilityForm docstring); an explicit value overrides it.
    tl['interest234AOverride'] = cleaned.get('interest234AOverride')
    tl['interest234BOverride'] = cleaned.get('interest234BOverride')
    tl['fee234FOverride'] = cleaned.get('fee234FOverride')


def tax_liability(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None

    if request.method == 'POST':
        form = TaxLiabilityForm(request.POST)
        conflict_message = _check_version_conflict(request, tax_return)
        if conflict_message:
            if _is_ajax(request):
                return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
        elif form.is_valid():
            before = copy.deepcopy(model)
            _apply_tax_liability_form(model, form.cleaned_data)
            _log_field_changes(tax_return, before, model, request.user if request.user.is_authenticated else None)
            tax_return.bump_version()

            action = request.POST.get('action', 'save')
            if action == 'confirm':
                report = validate(model, tier=2, screen='TAX_LIABILITY')
                if report.errors:
                    _set_screen_status(tax_return, 'TAX_LIABILITY', 'HAS_ERRORS')
                else:
                    _set_screen_status(tax_return, 'TAX_LIABILITY', 'CONFIRMED')
                tax_return.save()
                AuditLogEntry.objects.create(
                    tax_return=tax_return, actor=request.user if request.user.is_authenticated else None,
                    kind=AuditLogEntry.KIND_VALIDATION_RUN,
                    payload={'screen': 'TAX_LIABILITY', 'errors': [e.ruleId for e in report.errors]},
                )
                if not report.errors:
                    return redirect('itr1:tax_summary', return_id=return_id)
            else:
                _set_screen_status(tax_return, 'TAX_LIABILITY', 'IN_PROGRESS')
                tax_return.save()
                if _is_ajax(request):
                    return _ajax_saved_response(tax_return)
                return redirect('itr1:tax_liability', return_id=return_id)
    else:
        form = TaxLiabilityForm(initial=_tax_liability_initial(model))

    computed = compute(model)

    return render(request, 'itr1/tax_liability.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Tax Liability',
        'form': form,
        'return_id': return_id,
        'computed': computed,
        'tax': computed['tax'],
        'interest': computed['interest'],
        'total_tax_fee_interest': computed['totalTaxFeeAndInterest'],
        'total_tax_fee_interest_display': format_indian(computed['totalTaxFeeAndInterest']),
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return, computed),
    })


def tax_summary(request, return_id):
    tax_return = _get_return(request, return_id)

    if request.method == 'POST' and request.POST.get('action') == 'proceed':
        _set_screen_status(tax_return, 'TAX_SUMMARY', 'CONFIRMED')
        tax_return.save()
        return redirect('itr1:validation', return_id=return_id)

    if request.method == 'POST' and request.POST.get('action') == 'export_pdf':
        computed = compute(tax_return.data)
        pdf_bytes = render_computation_sheet_pdf(tax_return, computed)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="ITR1_computation_sheet_{return_id}.pdf"'
        return response

    def extra(tr):
        computed = compute(tr.data)
        deduction_lines = [
            {'section': section, 'amount': info['eligible'], 'amount_display': format_indian(info['eligible'])}
            for section, info in computed['deductions']['bySection'].items()
        ]
        display = {
            'salary': format_indian(computed['salary']['incomeFromSalary']),
            'houseProperty': format_indian(computed['houseProperty']['incomeForGti']),
            'otherSources': format_indian(computed['otherSources']['netIncomeOthSrc']),
            'ltcg112A': format_indian(computed['ltcg112A']),
            'grossTotalIncome': format_indian(computed['grossTotalIncomeInclLtcg']),
            'totalDeductions': format_indian(computed['totalDeductions']),
            'totalIncome': format_indian(computed['totalIncome']),
            'taxPayableOnTotalIncome': format_indian(computed['tax']['taxPayableOnTotalIncome']),
            'rebate87A': format_indian(computed['tax']['rebate87A']),
            'taxPayableAfterRebate': format_indian(computed['tax']['taxPayableAfterRebate']),
            'educationCess': format_indian(computed['tax']['educationCess']),
            'totalTaxAndCess': format_indian(computed['tax']['totalTaxAndCess']),
            'relief89': format_indian(computed['tax']['relief89']),
            'balanceTaxAfterRelief': format_indian(computed['tax']['balanceTaxAfterRelief']),
            'interest234A': format_indian(computed['interest']['interest234A']),
            'interest234B': format_indian(computed['interest']['interest234B']),
            'interest234C': format_indian(computed['interest']['interest234C']),
            'fee234F': format_indian(computed['interest']['fee234F']),
            'fee234I': format_indian(computed['interest']['fee234I']),
            'totalTaxFeeAndInterest': format_indian(computed['totalTaxFeeAndInterest']),
            'tds1': format_indian(computed['taxesPaid']['tds1']),
            'tds2': format_indian(computed['taxesPaid']['tds2']),
            'tds3': format_indian(computed['taxesPaid']['tds3']),
            'tcs': format_indian(computed['taxesPaid']['tcs']),
            'advanceTax': format_indian(computed['taxesPaid']['advanceTax']),
            'selfAssessmentTax': format_indian(computed['taxesPaid']['selfAssessmentTax']),
            'totalTaxesPaid': format_indian(computed['taxesPaid']['total']),
            'refundDue': format_indian(computed['refundDue']),
            'balanceTaxPayable': format_indian(computed['balanceTaxPayable']),
        }
        return {'computed': computed, 'deduction_lines': deduction_lines, 'display': display}

    return _screen_view(request, return_id, 'tax_summary', 'Tax Summary',
                         template='itr1/tax_summary.html', extra=extra)


def validation(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data

    if request.method == 'POST':
        action = request.POST.get('action')
        actor = request.user if request.user.is_authenticated else None

        if action == 'acknowledge':
            acks = model.setdefault('advisoryAcknowledgements', {})
            acknowledged_ids = []
            for key in request.POST:
                if key.startswith('ack_') and request.POST.get(key) == 'on':
                    rule_id = key[len('ack_'):]
                    acks[rule_id] = {
                        'by': actor.username if actor else 'demo',
                        'at': timezone.now().isoformat(),
                    }
                    acknowledged_ids.append(rule_id)
            tax_return.save()
            AuditLogEntry.objects.create(
                tax_return=tax_return, actor=actor, kind=AuditLogEntry.KIND_ADVISORY_ACK,
                payload={'acknowledgedRuleIds': acknowledged_ids},
            )
            return redirect('itr1:validation', return_id=return_id)

        if action == 'download':
            computed = compute(model)
            try:
                result = generate_json_or_throw(model, {'computed': computed})
            except GenerationBlockedError:
                return redirect('itr1:validation', return_id=return_id)
            AuditLogEntry.objects.create(
                tax_return=tax_return, actor=actor, kind=AuditLogEntry.KIND_JSON_GENERATION,
                payload={'filename': result.filename, 'sha256': result.sha256},
                new_value=model,
            )
            response = HttpResponse(result.json, content_type='application/json')
            response['Content-Disposition'] = f'attachment; filename="{result.filename}"'
            return response

        if action == 'preview':
            computed = compute(model)
            pdf_bytes = render_return_preview_pdf(tax_return, computed)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="ITR1_preview_{return_id}.pdf"'
            return response

        if action == 'export_report':
            computed = compute(model)
            result = generate_json(model, {'computed': computed})
            pdf_bytes = render_validation_report_pdf(tax_return, result.validation)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="ITR1_validation_report_{return_id}.pdf"'
            return response

    computed = compute(model)
    result = generate_json(model, {'computed': computed})
    report = result.validation

    # §3.2 deep links: "Go to field" scrolls to, highlights and focuses the
    # offending section (see base.html's deep-link JS and itr1/deep_links.py).
    for finding in report.errors + report.advisories + report.documentAdvisories:
        finding.goto_url = resolve_deep_link(return_id, finding.deepLink)

    return render(request, 'itr1/validation.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Validation & JSON',
        'return_id': return_id,
        'computed': computed,
        'report': report,
        'generation': result,
        'pending_ack_ids': set(result.pendingAcknowledgements),
        'downloadable': result.downloadable and not result.pendingAcknowledgements,
        **_chrome_context(tax_return, computed),
    })
