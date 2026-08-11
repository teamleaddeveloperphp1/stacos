"""TaxFiler API. Mounted at top-level /api/v1/members/, NOT under /itr/ --
a member is a person the account holder files for across every service
(ITR, TDS, GST, ...), not an ITR-specific concept, even though TaxFiler the
model currently lives in itr/models.py (see Phase 4 plan's "explicitly out
of scope": moving it is deliberately deferred, not forgotten)."""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from itr.forms import TaxFilerForm
from itr.models import TaxFiler, TaxReturn
from .serializers import taxfiler_to_dict

_FILER_FIELDS = ('pan', 'dob', 'email', 'first_name', 'middle_name', 'last_name', 'gender', 'father_name', 'mobile_number')


@api_view(['GET', 'POST'])
def members_list(request):
    if request.method == 'GET':
        filers = TaxFiler.objects.filter(owner=request.user)
        return Response({'results': [taxfiler_to_dict(f) for f in filers]})

    form = TaxFilerForm(data=request.data)
    if not form.is_valid():
        return Response({'errors': form.errors}, status=400)
    filer = TaxFiler.objects.create(owner=request.user, **form.cleaned_data)
    return Response(taxfiler_to_dict(filer), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
def member_detail(request, member_id):
    # .get() (not get_object_or_404) -- TaxFiler.DoesNotExist is caught by
    # the same itr.api.v1.exceptions.exception_handler as TaxReturn's, so a
    # non-owned/nonexistent member 404s the same way everything else does.
    filer = TaxFiler.objects.get(pk=member_id, owner=request.user)

    if request.method == 'GET':
        return Response(taxfiler_to_dict(filer))

    if request.method == 'DELETE':
        if TaxReturn.objects.filter(owner=filer.owner, pan=filer.pan).exists():
            return Response(
                {'detail': f'Cannot delete {filer.first_name} {filer.last_name} -- a return already exists for this PAN.'},
                status=409,
            )
        filer.delete()
        return Response(status=204)

    # PATCH: TaxFilerForm validates a full record, so a partial body is
    # merged onto the current values first -- the client only sends what
    # changed, but coercion/validation still runs against the complete set.
    current = {field: getattr(filer, field) for field in _FILER_FIELDS}
    form = TaxFilerForm(data={**current, **request.data})
    if not form.is_valid():
        return Response({'errors': form.errors}, status=400)
    for field, value in form.cleaned_data.items():
        setattr(filer, field, value)
    filer.save()
    return Response(taxfiler_to_dict(filer))
