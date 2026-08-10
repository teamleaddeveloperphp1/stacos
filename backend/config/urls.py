"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView


def healthz(request):
    return HttpResponse('ok')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', healthz, name='healthz'),
    path('accounts/', include('accounts.urls')),
    # Mounted at project level, not nested in accounts.urls's app_name
    # namespace -- django-simple-captcha's own helpers call
    # reverse("captcha-image", ...) unnamespaced, which breaks if these
    # patterns are included underneath an app_name.
    path('accounts/captcha/', include('captcha.urls')),
    path('', include('services.urls')),
    path('', RedirectView.as_view(pattern_name='services:dashboard', permanent=False)),
    path('', include('itr.urls')),
]
