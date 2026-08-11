"""Every view here calls exactly one itr.services.return_service function
(plus, for screens, a itr.api.v1.screen_payloads builder to validate/coerce
the JSON body first) and does nothing else -- no model mutation, no
compute()/validate() call, no audit write lives in this file.

Money: every service function already returns plain ints (Phase 3). Nothing
in this file re-formats anything, so nothing here can leak a ₹/comma back
in.
"""

import json

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.itr.forms import VerificationForm
from apps.itr.models import TaxReturn
from apps.itr.services import return_service
from .screen_payloads import SCREEN_PAYLOAD_BUILDERS, build_filing_section_payload
from .serializers import return_summary_to_dict, validation_report_to_dict

_DOCUMENT_EXPORTERS = {
    'validation-report': return_service.export_validation_report_pdf,
    'computation-sheet': return_service.export_computation_sheet_pdf,
    'preview': return_service.export_return_preview_pdf,
}


def _screen_key(raw):
    """URL path segments are lowercase-hyphenated ("total-deductions"); the
    service layer's _SCREEN_HANDLERS keys are SCREAMING_SNAKE ("TOTAL_
    DEDUCTIONS") -- same names itr/views.py and validate()'s `screen`
    rule-filter already use."""
    return raw.upper().replace('-', '_')


def _ensure_owned(return_id, user):
    """Confirms the return exists and belongs to this user, raising
    TaxReturn.DoesNotExist (-> 404 via the exception handler) otherwise.

    Every view whose first step is normally return_service._get_owned_return
    gets this ownership check "for free" as its first statement, but four
    views (filing_section_view, screen_detail's PUT, screen_confirm,
    save_verification_view) validate the request body with a local
    form/builder BEFORE ever calling into the service layer -- so a
    non-owner posting a malformed body got a 400 instead of the 404 every
    other endpoint guarantees for cross-owner access. Call this first in
    those views so ownership is checked before body validation, regardless
    of whether the body turns out to be valid."""
    TaxReturn.objects.only('id').get(pk=return_id, owner=user)


def _expected_version(request):
    """The client's last-known version, for the optimistic-lock check --
    a body field, not a header, so it travels with the payload in one
    place. Absent (None) means "don't check", same as the web path when
    a screen has no _version field at all (see itr.views.filing_section)."""
    value = request.data.get('version') if hasattr(request.data, 'get') else None
    return int(value) if value is not None else None


@api_view(['GET', 'POST'])
def returns_list(request):
    if request.method == 'GET':
        qs = TaxReturn.objects.filter(owner=request.user).order_by('-updated_at')
        return Response({'results': [return_summary_to_dict(r) for r in qs]})

    tax_return = TaxReturn.objects.create(owner=request.user)
    return Response(return_summary_to_dict(tax_return), status=201)


@api_view(['GET'])
def return_detail(request, return_id):
    result = return_service.get_return(return_id, request.user)
    return Response(result)


@api_view(['PUT'])
def filing_section_view(request, return_id):
    """Not one of the plan's Step 4 table rows -- added because
    itr.views.filing_section turned out to still be mutating the model
    directly (a Phase 3 gap fixed alongside this endpoint, see
    return_service.save_filing_section). Included so "every operation the
    web UI can perform" stays true; flagged in the Phase 4 report as an
    addition beyond the literal endpoint table."""
    _ensure_owned(return_id, request.user)
    payload, errors = build_filing_section_payload(request.data)
    if errors:
        return Response({'errors': errors}, status=400)
    result = return_service.save_filing_section(return_id, request.user, payload, _expected_version(request))
    return Response({'version': result['version']})


@api_view(['GET', 'PUT'])
def screen_detail(request, return_id, screen):
    screen_key = _screen_key(screen)
    builder = SCREEN_PAYLOAD_BUILDERS.get(screen_key)
    if builder is None:
        return Response({'detail': f'Unknown screen "{screen}".'}, status=404)

    if request.method == 'GET':
        result = return_service.get_return(return_id, request.user)
        return Response(result)

    _ensure_owned(return_id, request.user)
    payload, errors = builder(request.data)
    if errors:
        return Response({'errors': errors}, status=400)
    result = return_service.save_screen(return_id, request.user, screen_key, payload, _expected_version(request))
    return Response({
        'version': result['version'],
        'screen_status': result['screen_status'],
        'computed': result['computed'],
        'model': result['model'],
    })


@api_view(['POST'])
def screen_confirm(request, return_id, screen):
    screen_key = _screen_key(screen)
    builder = SCREEN_PAYLOAD_BUILDERS.get(screen_key)
    if builder is None:
        return Response({'detail': f'Unknown screen "{screen}".'}, status=404)

    _ensure_owned(return_id, request.user)
    payload, errors = builder(request.data)
    if errors:
        return Response({'errors': errors}, status=400)
    result = return_service.confirm_screen(return_id, request.user, screen_key, payload, _expected_version(request))
    # confirmed=False here means the request was well-formed and the write
    # succeeded, but tier-2 rules (or, for PERSONAL_INFO, the bank-account
    # structural check) blocked confirmation -- a business result, not a
    # client error, so this is 200 either way (matching the web path, which
    # re-renders 200 rather than raising on the same condition).
    return Response({
        'version': result['version'],
        'confirmed': result['confirmed'],
        'bank_errors': result['bank_errors'],
        'computed': result['computed'],
        **validation_report_to_dict(result['report']),
    })


@api_view(['POST'])
def save_verification_view(request, return_id):
    _ensure_owned(return_id, request.user)
    form = VerificationForm(data=request.data)
    if not form.is_valid():
        return Response({'errors': form.errors}, status=400)
    result = return_service.save_verification(return_id, request.user, form.cleaned_data)
    return Response(result)


@api_view(['POST'])
def confirm_tax_summary_view(request, return_id):
    result = return_service.confirm_tax_summary(return_id, request.user)
    return Response(result)


@api_view(['GET'])
def computation_view(request, return_id):
    computed = return_service.get_computation(return_id, request.user)
    return Response(computed)


@api_view(['POST'])
def validate_view(request, return_id):
    result = return_service.run_validation(return_id, request.user)
    return Response({
        'downloadable': result['downloadable'],
        'pending_acknowledgements': result['pending_acknowledgements'],
        **validation_report_to_dict(result['report']),
    })


@api_view(['POST'])
def generate_json_view(request, return_id):
    result = return_service.generate_return_json(return_id, request.user)
    payload = json.loads(result['json'])

    if request.query_params.get('download') == '1':
        response = HttpResponse(result['json'], content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{result["filename"]}"'
        return response

    return Response({'filename': result['filename'], 'sha256': result['sha256'], 'payload': payload})


@api_view(['POST'])
def import_json_view(request, return_id):
    result = return_service.import_return_json(return_id, request.user, request.data)
    return Response(result)


@api_view(['POST'])
def acknowledge_view(request, return_id):
    rule_ids = request.data.get('rule_ids') or []
    result = return_service.acknowledge_advisories(return_id, request.user, rule_ids)
    return Response(result)


@api_view(['GET'])
def regime_comparison_view(request, return_id):
    result = return_service.regime_comparison(return_id, request.user)
    return Response(result)


@api_view(['GET'])
def document_view(request, return_id, kind):
    exporter = _DOCUMENT_EXPORTERS.get(kind)
    if exporter is None:
        return Response({'detail': f'Unknown document kind "{kind}".'}, status=404)
    pdf_bytes = exporter(return_id, request.user)
    return HttpResponse(pdf_bytes, content_type='application/pdf')
