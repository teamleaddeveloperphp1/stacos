from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.catalog import CATALOG
from catalog.models import ServiceInterest

User = get_user_model()


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='svc1', email='svc1@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_dashboard_renders_seven_cards(self):
        response = self.client.get(reverse('catalog:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['cards']), 7)

    def test_itr_links_to_members_landing_page(self):
        response = self.client.get(reverse('catalog:dashboard'))
        itr_card = next(c for c in response.context['cards'] if c['service'].slug == 'itr')
        self.assertEqual(itr_card['url'], reverse('itr:member_list'))

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('catalog:dashboard'))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('catalog:dashboard')}")


class ServicePageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='svc2', email='svc2@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_each_coming_soon_slug_returns_200(self):
        for service in CATALOG:
            if service.available:
                continue
            response = self.client.get(reverse('catalog:service', args=[service.slug]))
            self.assertEqual(response.status_code, 200, service.slug)
            self.assertContains(response, 'Coming soon')

    def test_unknown_slug_returns_200_with_same_template(self):
        response = self.client.get(reverse('catalog:service', args=['totally-made-up']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Coming soon')

    def test_notify_me_records_interest(self):
        url = reverse('catalog:service', args=['esic'])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ServiceInterest.objects.filter(user=self.user, slug='esic').exists())
        self.assertContains(response, "We'll let you know.")
