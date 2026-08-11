"""GET /api/v1/services/ -- the same seven services the web dashboard
renders, read from the same CATALOG list (catalog/catalog.py). Do not
hardcode a second list here: catalog_parity test in
tests/catalog/test_api_v1.py asserts the web dashboard and this endpoint
list identical slugs in the same order, which is only guaranteed by
sharing the one source."""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from catalog.catalog import CATALOG


def _service_to_dict(service):
    return {
        'slug': service.slug,
        'name': service.name,
        'description': service.description,
        'status': 'available' if service.available else 'coming_soon',
        'icon': service.icon,
        'api_base': service.api_base,
    }


@api_view(['GET'])
def services_list(request):
    # Default permission (IsAuthenticated, see REST_FRAMEWORK in settings)
    # applies -- the catalog carries no per-user data, but the web
    # dashboard it mirrors is login-gated (AccessControlMiddleware), so
    # this endpoint stays login-gated too rather than introducing a
    # public/private inconsistency between the two.
    return Response({'services': [_service_to_dict(s) for s in CATALOG]})
