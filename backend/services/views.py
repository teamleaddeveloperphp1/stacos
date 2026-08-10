import logging

from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.generic import TemplateView

from services.catalog import CATALOG, get_service
from services.models import ServiceInterest

logger = logging.getLogger(__name__)


class DashboardView(TemplateView):
    template_name = 'services/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cards = []
        for service in CATALOG:
            url = reverse(service.url_name) if service.available else reverse('services:service', args=[service.slug])
            cards.append({'service': service, 'url': url})
        ctx['cards'] = cards
        return ctx


@method_decorator(csrf_protect, name='dispatch')
class ServiceView(View):
    """§9.1: always 200 -- available services never route here (the
    dashboard links straight to their real URL), and an unknown slug gets
    the same coming-soon template rather than a 404."""

    template_name = 'services/coming_soon.html'

    def get(self, request, slug):
        service = get_service(slug)
        if service is None:
            logger.info('Unknown service slug requested: %s', slug)
        interested = request.user.is_authenticated and ServiceInterest.objects.filter(
            user=request.user, slug=slug,
        ).exists()
        return self.render(request, service, slug, interested)

    def post(self, request, slug):
        service = get_service(slug)
        if request.user.is_authenticated:
            ServiceInterest.objects.get_or_create(user=request.user, slug=slug)
        return self.render(request, service, slug, interested=True)

    def render(self, request, service, slug, interested):
        name = service.name if service else slug
        return render(request, self.template_name, {
            'service_name': name,
            'slug': slug,
            'interested': interested,
        })
