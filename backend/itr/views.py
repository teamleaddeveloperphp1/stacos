from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from itr.serialize.generate import GenerationBlockedError
from itr.services import return_service
from itr.services.return_service import VersionConflictError
from itr.forms import (
    BankAccountFormSet,
    ChallanFormSet,
    DeductionsForm,
    Disability80DDUForm,
    ExemptAllowanceFormSet,
    ExemptIncomeFormSet,
    HousePropertyFormSet,
    HraForm,
    OtherSourceFormSet,
    FilingSectionForm,
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
    TaxFilerForm,
    TaxLiabilityForm,
    VerificationForm,
    TcsFormSet,
    Tds1FormSet,
    Tds2FormSet,
    Tds3FormSet,
)
from itr.models import TaxFiler, TaxReturn
from itr.rules.registry import RULE_SET_VERSION
from itr.screens import build_menu_items
from itr.serialize.json_schema_validator import SCHEMA_VERSION
from itr.util.num import format_indian, format_rupees

_RETURN_FILE_SEC_LABELS = dict(RETURN_FILE_SEC_CHOICES)


def _chrome_context(tax_return, computed=None):
    """Global chrome shown on every screen (§3.3): taxpayer name/PAN/AY/filing
    section, the derived regime badge, a live refund/payable ticker, and the
    rule-set/schema/constants versions + draft save status for the footer.
    Numbers come from the service layer, not a direct compute() call here,
    so this reads the same figures the API will."""
    model = tax_return.data
    computed = computed if computed is not None else return_service.get_computation(tax_return.pk, tax_return.owner)
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
    """Real auth now guards every /returns/ URL (accounts.middleware.
    AccessControlMiddleware) -- request.user is always authenticated by the
    time a view runs here."""
    return request.user


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

    return render(request, 'itr/return_list.html', {'cards': cards})


def return_create(request):
    user = _current_user(request)
    tax_return = TaxReturn.objects.create(owner=user)
    return redirect('itr:filing_section', return_id=tax_return.pk)


def filing_section(request, return_id):
    """Gate screen shown before Personal Information: filing section + tax
    regime, answered on their own since they decide which fields the rest
    of the return even shows."""
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    fs = model['filingStatus']

    if request.method == 'POST':
        form = FilingSectionForm(request.POST)
        if form.is_valid():
            result = return_service.save_filing_section(
                return_id, request.user, form.cleaned_data, _expected_version(request),
            )
            _sync_tax_return(tax_return, result)
            return redirect('itr:personal_info', return_id=return_id)
    else:
        form = FilingSectionForm(initial={
            'return_file_sec': fs['returnFileSec'],
            'opt_out_of_new_regime': fs['optOutOfNewRegime'] or 'N',
        })

    return render(request, 'itr/filing_section.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Filing Section',
        'form': form,
        'return_id': return_id,
        **_chrome_context(tax_return),
    })


MEMBERS_PAGE_SIZE = 5


def _get_filer(request, member_id):
    return get_object_or_404(TaxFiler, pk=member_id, owner=_current_user(request))


def member_list(request):
    user = _current_user(request)
    filers = TaxFiler.objects.filter(owner=user)
    if not filers.exists():
        return redirect('itr:member_add')

    page_number = request.GET.get('page', 1)
    page = Paginator(filers, MEMBERS_PAGE_SIZE).get_page(page_number)
    return render(request, 'itr/member_list.html', {'page': page})


def member_add(request):
    if request.method == 'POST':
        form = TaxFilerForm(request.POST)
        if form.is_valid():
            TaxFiler.objects.create(owner=_current_user(request), **form.cleaned_data)
            return redirect('itr:member_list')
    else:
        form = TaxFilerForm()
    return render(request, 'itr/member_form.html', {'form': form, 'is_edit': False})


def member_edit(request, member_id):
    filer = _get_filer(request, member_id)
    if request.method == 'POST':
        form = TaxFilerForm(request.POST)
        if form.is_valid():
            for field, value in form.cleaned_data.items():
                setattr(filer, field, value)
            filer.save()
            return redirect('itr:member_list')
    else:
        form = TaxFilerForm(initial={
            'pan': filer.pan, 'dob': filer.dob, 'email': filer.email,
            'first_name': filer.first_name, 'middle_name': filer.middle_name, 'last_name': filer.last_name,
            'gender': filer.gender, 'father_name': filer.father_name, 'mobile_number': filer.mobile_number,
        })
    return render(request, 'itr/member_form.html', {'form': form, 'is_edit': True, 'filer': filer})


def member_delete(request, member_id):
    if request.method != 'POST':
        return redirect('itr:member_list')
    filer = _get_filer(request, member_id)
    if TaxReturn.objects.filter(owner=filer.owner, pan=filer.pan).exists():
        messages.error(request, f'Cannot delete {filer.first_name} {filer.last_name} — a return already exists for this PAN.')
    else:
        filer.delete()
    return redirect('itr:member_list')


def member_continue(request, member_id):
    filer = _get_filer(request, member_id)
    tax_return = TaxReturn.objects.filter(owner=filer.owner, pan=filer.pan, ay='2026-27').order_by('-updated_at').first()
    if tax_return is None:
        tax_return = TaxReturn.objects.create(owner=filer.owner, pan=filer.pan)
        pi = tax_return.data['personalInfo']
        pi['firstName'] = filer.first_name
        pi['middleName'] = filer.middle_name
        pi['lastName'] = filer.last_name
        pi['pan'] = filer.pan
        pi['dob'] = filer.dob.isoformat()
        pi['contact']['primaryEmail'] = filer.email
        pi['contact']['primaryMobile'] = filer.mobile_number
        tax_return.save(update_fields=['data', 'pan'])
    return redirect('itr:filing_section', return_id=tax_return.pk)


def _get_return(request, return_id):
    user = _current_user(request)
    return get_object_or_404(TaxReturn, pk=return_id, owner=user)


def _screen_status(tax_return):
    return tax_return.data.get('screenStatus', {})


def _is_ajax(request):
    """§3.3 autosave (every 20s + on blur) posts in the background via
    fetch(); it must never navigate the page away from under the preparer,
    so these requests get a small JSON response instead of a redirect."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _expected_version(request):
    raw = request.POST.get('_version')
    return int(raw) if raw is not None else None


def _ajax_saved_response(result):
    return JsonResponse({
        'saved': True,
        'version': result['version'],
        'savedAt': result['updated_at'].strftime('%H:%M:%S'),
    })


def _format_regime_comparison(raw):
    return {'NEW': format_indian(raw['NEW']), 'OLD': format_indian(raw['OLD'])}


def _sync_tax_return(tax_return, result):
    """After a non-redirecting save_screen/confirm_screen call, bring the
    view's already-loaded tax_return object's in-memory state up to date
    from the service's return value -- no second DB round-trip, and no
    "did the caller remember to re-read?" question for anything built on
    top of this later."""
    tax_return.data = result['model']
    tax_return.version = result['version']
    tax_return.updated_at = result['updated_at']


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


def personal_info(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    bank_errors = []
    conflict_message = None
    report = None
    computed = None

    if request.method == 'POST':
        form = PersonalInfoForm(request.POST)
        formset = BankAccountFormSet(request.POST, prefix='bank')
        if form.is_valid() and formset.is_valid():
            payload = {
                'personal_info': form.cleaned_data,
                'bank_accounts': [f.cleaned_data for f in formset],
            }
            action = request.POST.get('action', 'save')
            try:
                if action == 'confirm':
                    result = return_service.confirm_screen(
                        return_id, request.user, 'PERSONAL_INFO', payload, _expected_version(request),
                    )
                    report = result['report']
                    bank_errors = result['bank_errors']
                    if result['confirmed']:
                        return redirect('itr:gross_total_income', return_id=return_id)
                else:
                    result = return_service.save_screen(
                        return_id, request.user, 'PERSONAL_INFO', payload, _expected_version(request),
                    )
                    if _is_ajax(request):
                        return _ajax_saved_response(result)
                    return redirect('itr:personal_info', return_id=return_id)
                _sync_tax_return(tax_return, result)
                model = tax_return.data
                computed = result['computed']
            except VersionConflictError as e:
                conflict_message = e.message
                if _is_ajax(request):
                    return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
    else:
        form = PersonalInfoForm(initial=_personal_info_initial(model))
        formset = BankAccountFormSet(initial=_bank_accounts_initial(model), prefix='bank')

    regime_comparison = _format_regime_comparison(return_service.regime_comparison(return_id, request.user))

    return render(request, 'itr/personal_info.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Personal Information',
        'regime_comparison': regime_comparison,
        'form': form,
        'formset': formset,
        'return_id': return_id,
        'bank_errors': bank_errors,
        'conflict_message': conflict_message,
        'report': report,
        **_chrome_context(tax_return, computed),
    })


def _screen_view(request, return_id, screen_id, label, template='itr/screen_placeholder.html', extra=None):
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
    h = inc['hra10_13A']
    hra = {
        'place_of_work': h['placeOfWork'],
        'actual_hra_received': h['actualHraReceived'],
        'actual_rent_paid': h['actualRentPaid'],
        'basic_salary': h['basicSalary'],
        'dearness_allowance': h['dearnessAllowance'],
    }
    exempt_allowances = [
        {'nature': r['nature'], 'amount': r['amount']}
        for r in inc.get('exemptAllowances', [])
    ]
    properties = [
        {
            'property_type': p['propertyType'],
            'property_owner': p.get('propertyOwner', ''),
            'flat_door_building': p.get('address', {}).get('flatDoorBuilding', ''),
            'area_locality': p.get('address', {}).get('areaLocality', ''),
            'town_city_district': p.get('address', {}).get('townCityDistrict', ''),
            'state_code': p.get('address', {}).get('stateCode', ''),
            'pin_code': p.get('address', {}).get('pinCode', ''),
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
    return salary, hra, exempt_allowances, properties, other_sources, exempt_income


def gross_total_income(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None
    computed = None

    if request.method == 'POST':
        salary_form = SalaryForm(request.POST)
        hra_form = HraForm(request.POST)
        allowance_formset = ExemptAllowanceFormSet(request.POST, prefix='allow')
        property_formset = HousePropertyFormSet(request.POST, prefix='hp')
        other_source_formset = OtherSourceFormSet(request.POST, prefix='os')
        exempt_income_formset = ExemptIncomeFormSet(request.POST, prefix='ei')

        forms_valid = (
            salary_form.is_valid()
            and hra_form.is_valid()
            and allowance_formset.is_valid()
            and property_formset.is_valid()
            and other_source_formset.is_valid()
            and exempt_income_formset.is_valid()
        )
        if forms_valid:
            payload = {
                'salary': salary_form.cleaned_data,
                'hra': hra_form.cleaned_data,
                'allowances': [f.cleaned_data for f in allowance_formset],
                'properties': [f.cleaned_data for f in property_formset],
                'other_sources': [f.cleaned_data for f in other_source_formset],
                'exempt_income': [f.cleaned_data for f in exempt_income_formset],
            }
            action = request.POST.get('action', 'save')
            try:
                if action == 'confirm':
                    result = return_service.confirm_screen(
                        return_id, request.user, 'GROSS_TOTAL_INCOME', payload, _expected_version(request),
                    )
                    report = result['report']
                    if result['confirmed']:
                        return redirect('itr:total_deductions', return_id=return_id)
                else:
                    result = return_service.save_screen(
                        return_id, request.user, 'GROSS_TOTAL_INCOME', payload, _expected_version(request),
                    )
                    if _is_ajax(request):
                        return _ajax_saved_response(result)
                    return redirect('itr:gross_total_income', return_id=return_id)
                _sync_tax_return(tax_return, result)
                model = tax_return.data
                computed = result['computed']
            except VersionConflictError as e:
                conflict_message = e.message
                if _is_ajax(request):
                    return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
    else:
        salary_initial, hra_initial, allowances_initial, properties_initial, other_sources_initial, exempt_income_initial = _gti_initial(model)
        salary_form = SalaryForm(initial=salary_initial)
        hra_form = HraForm(initial=hra_initial)
        allowance_formset = ExemptAllowanceFormSet(initial=allowances_initial, prefix='allow')
        property_formset = HousePropertyFormSet(initial=properties_initial, prefix='hp')
        other_source_formset = OtherSourceFormSet(initial=other_sources_initial, prefix='os')
        exempt_income_formset = ExemptIncomeFormSet(initial=exempt_income_initial, prefix='ei')

    if computed is None:
        computed = return_service.get_computation(return_id, request.user)

    return render(request, 'itr/gross_total_income.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Gross Total Income',
        'salary_form': salary_form,
        'hra_form': hra_form,
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


def total_deductions(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None
    computed = None

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
        if forms_valid:
            payload = {
                'deductions': deductions_form.cleaned_data,
                'schedule_80c': [f.cleaned_data for f in sched80c_fs],
                'schedule_80ccc': [f.cleaned_data for f in sched80ccc_fs],
                'schedule_80d': sched80d_form.cleaned_data,
                'disability_80dd': disability_80dd_form.cleaned_data,
                'disability_80u': disability_80u_form.cleaned_data,
                'schedule_80e': [f.cleaned_data for f in sched80e_fs],
                'schedule_80ee': [f.cleaned_data for f in sched80ee_fs],
                'schedule_80eea': [f.cleaned_data for f in sched80eea_fs],
                'schedule_80eeb': [f.cleaned_data for f in sched80eeb_fs],
                'schedule_80g': [f.cleaned_data for f in sched80g_fs],
                'schedule_80gga': [f.cleaned_data for f in sched80gga_fs],
                'schedule_80ggc': [f.cleaned_data for f in sched80ggc_fs],
            }
            action = request.POST.get('action', 'save')
            try:
                if action == 'confirm':
                    result = return_service.confirm_screen(
                        return_id, request.user, 'TOTAL_DEDUCTIONS', payload, _expected_version(request),
                    )
                    report = result['report']
                    if result['confirmed']:
                        return redirect('itr:tax_paid', return_id=return_id)
                else:
                    result = return_service.save_screen(
                        return_id, request.user, 'TOTAL_DEDUCTIONS', payload, _expected_version(request),
                    )
                    if _is_ajax(request):
                        return _ajax_saved_response(result)
                    return redirect('itr:total_deductions', return_id=return_id)
                _sync_tax_return(tax_return, result)
                model = tax_return.data
                computed = result['computed']
            except VersionConflictError as e:
                conflict_message = e.message
                if _is_ajax(request):
                    return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
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

    if computed is None:
        computed = return_service.get_computation(return_id, request.user)

    return render(request, 'itr/total_deductions.html', {
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


def tax_paid(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None
    computed = None

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
        if forms_valid:
            payload = {
                'tds1': [f.cleaned_data for f in tds1_fs],
                'tds2': [f.cleaned_data for f in tds2_fs],
                'tds3': [f.cleaned_data for f in tds3_fs],
                'tcs': [f.cleaned_data for f in tcs_fs],
                'challans': [f.cleaned_data for f in challan_fs],
            }
            action = request.POST.get('action', 'save')
            try:
                if action == 'confirm':
                    result = return_service.confirm_screen(
                        return_id, request.user, 'TAX_PAID', payload, _expected_version(request),
                    )
                    report = result['report']
                    if result['confirmed']:
                        return redirect('itr:tax_liability', return_id=return_id)
                else:
                    result = return_service.save_screen(
                        return_id, request.user, 'TAX_PAID', payload, _expected_version(request),
                    )
                    if _is_ajax(request):
                        return _ajax_saved_response(result)
                    return redirect('itr:tax_paid', return_id=return_id)
                _sync_tax_return(tax_return, result)
                model = tax_return.data
                computed = result['computed']
            except VersionConflictError as e:
                conflict_message = e.message
                if _is_ajax(request):
                    return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
    else:
        initial = _tax_paid_initial(model)
        tds1_fs = Tds1FormSet(initial=initial['tds1'], prefix='tds1')
        tds2_fs = Tds2FormSet(initial=initial['tds2'], prefix='tds2')
        tds3_fs = Tds3FormSet(initial=initial['tds3'], prefix='tds3')
        tcs_fs = TcsFormSet(initial=initial['tcs'], prefix='tcs')
        challan_fs = ChallanFormSet(initial=initial['challans'], prefix='challan')

    if computed is None:
        computed = return_service.get_computation(return_id, request.user)

    return render(request, 'itr/tax_paid.html', {
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


def tax_liability(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    conflict_message = None
    report = None
    computed = None

    if request.method == 'POST':
        form = TaxLiabilityForm(request.POST)
        if form.is_valid():
            payload = {'tax_liability': form.cleaned_data}
            action = request.POST.get('action', 'save')
            try:
                if action == 'confirm':
                    result = return_service.confirm_screen(
                        return_id, request.user, 'TAX_LIABILITY', payload, _expected_version(request),
                    )
                    report = result['report']
                    if result['confirmed']:
                        return redirect('itr:tax_summary', return_id=return_id)
                else:
                    result = return_service.save_screen(
                        return_id, request.user, 'TAX_LIABILITY', payload, _expected_version(request),
                    )
                    if _is_ajax(request):
                        return _ajax_saved_response(result)
                    return redirect('itr:tax_liability', return_id=return_id)
                _sync_tax_return(tax_return, result)
                model = tax_return.data
                computed = result['computed']
            except VersionConflictError as e:
                conflict_message = e.message
                if _is_ajax(request):
                    return JsonResponse({'saved': False, 'conflict': conflict_message}, status=409)
    else:
        form = TaxLiabilityForm(initial=_tax_liability_initial(model))

    if computed is None:
        computed = return_service.get_computation(return_id, request.user)

    return render(request, 'itr/tax_liability.html', {
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
    # Ownership/404 gate before any service call -- TaxReturn.DoesNotExist
    # from the service layer isn't auto-converted to a 404 response the way
    # get_object_or_404 is, so this check has to happen here regardless of
    # whether the object itself is used below (it isn't; _screen_view does
    # its own fetch for that).
    _get_return(request, return_id)

    if request.method == 'POST' and request.POST.get('action') == 'proceed':
        return_service.confirm_tax_summary(return_id, request.user)
        return redirect('itr:validation', return_id=return_id)

    if request.method == 'POST' and request.POST.get('action') == 'export_pdf':
        pdf_bytes = return_service.export_computation_sheet_pdf(return_id, request.user)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="ITR1_computation_sheet_{return_id}.pdf"'
        return response

    def extra(tr):
        computed = return_service.get_computation(tr.pk, tr.owner)
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
                         template='itr/tax_summary.html', extra=extra)


def validation(request, return_id):
    tax_return = _get_return(request, return_id)
    model = tax_return.data
    verification_form = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'acknowledge':
            acknowledged_ids = [
                key[len('ack_'):] for key in request.POST
                if key.startswith('ack_') and request.POST.get(key) == 'on'
            ]
            return_service.acknowledge_advisories(return_id, request.user, acknowledged_ids)
            return redirect('itr:validation', return_id=return_id)

        if action == 'save_verification':
            verification_form = VerificationForm(request.POST)
            if verification_form.is_valid():
                return_service.save_verification(return_id, request.user, verification_form.cleaned_data)
                return redirect('itr:validation', return_id=return_id)
            # else fall through to the bottom render with the bound (invalid) form

        if action == 'download':
            try:
                result = return_service.generate_return_json(return_id, request.user)
            except GenerationBlockedError:
                return redirect('itr:validation', return_id=return_id)
            response = HttpResponse(result['json'], content_type='application/json')
            response['Content-Disposition'] = f'attachment; filename="{result["filename"]}"'
            return response

        if action == 'preview':
            pdf_bytes = return_service.export_return_preview_pdf(return_id, request.user)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="ITR1_preview_{return_id}.pdf"'
            return response

        if action == 'export_report':
            pdf_bytes = return_service.export_validation_report_pdf(return_id, request.user)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="ITR1_validation_report_{return_id}.pdf"'
            return response

    if verification_form is None:
        v = model['verification']
        verification_form = VerificationForm(initial={
            'assessee_ver_name': v['assesseeVerName'],
            'father_name': v['fatherName'],
            'assessee_ver_pan': v['assesseeVerPan'],
            'capacity': v['capacity'],
            'place': v['place'],
        })

    validation_result = return_service.run_validation(return_id, request.user)
    report = validation_result['report']
    computed = return_service.get_computation(return_id, request.user)

    return render(request, 'itr/validation.html', {
        'ay': model['ay'],
        'menu_items': build_menu_items(return_id, _screen_status(tax_return)),
        'page_title': 'Validation & JSON',
        'return_id': return_id,
        'computed': computed,
        'report': report,
        'verification_form': verification_form,
        'pending_ack_ids': set(validation_result['pending_acknowledgements']),
        'downloadable': validation_result['downloadable'],
        **_chrome_context(tax_return, computed),
    })
