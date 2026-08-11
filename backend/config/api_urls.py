"""/api/v1/ router. Each service gets its own namespace from the start --
adding TDS, GST, etc. later means one new `path('tds/', include(...))`
line here, never touching ITR's own urls.py.

Cross-service concepts (members, the service catalog) mount at this top
level, not nested under any one service's prefix, since they are not
owned by ITR even though some of their code currently lives in itr/ (see
itr/api/v1/members_urls.py's docstring)."""

from django.urls import include, path

urlpatterns = [
    path('itr/', include('itr.api.v1.urls')),
    path('members/', include('itr.api.v1.members_urls')),
    path('services/', include('catalog.api.v1.urls')),
    # path('tds/', include('tds.api.v1.urls')),  # <- when TDS lands
]
