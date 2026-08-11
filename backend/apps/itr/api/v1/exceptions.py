"""Central DRF exception handler.

DRF's default exception_handler converts Http404/PermissionDenied to proper
responses but lets a plain ObjectDoesNotExist (e.g. TaxReturn.DoesNotExist,
raised by every itr.services.return_service function via
_get_owned_return) propagate as an unhandled exception -- a 500, which also
leaks "this object exists but isn't yours" vs "this object doesn't exist"
through the error TYPE even though the response looks the same either way.
Mapping it here, once, is the API-side twin of the web layer's
get_object_or_404 pattern (see itr.views._get_return and
tests.itr.test_web_lifecycle.CrossOwnerAccessTests).
"""

from django.core.exceptions import ObjectDoesNotExist
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_exception_handler

from apps.itr.serialize.generate import GenerationBlockedError
from apps.itr.services.return_service import VersionConflictError


def exception_handler(exc, context):
    if isinstance(exc, ObjectDoesNotExist):
        return Response({'detail': 'Not found.'}, status=404)

    if isinstance(exc, VersionConflictError):
        return_id = context['view'].kwargs.get('return_id') if context.get('view') else None
        payload = {'detail': exc.message}
        if return_id is not None:
            from apps.itr.models import TaxReturn
            try:
                payload['version'] = TaxReturn.objects.only('version').get(pk=return_id).version
            except TaxReturn.DoesNotExist:
                pass
        return Response(payload, status=409)

    if isinstance(exc, GenerationBlockedError):
        from apps.itr.api.v1.serializers import validation_report_to_dict

        report = exc.result.validation
        return Response({
            'detail': 'Generation blocked: unresolved errors or un-acknowledged advisories.',
            **validation_report_to_dict(report),
        }, status=422)

    return drf_default_exception_handler(exc, context)
