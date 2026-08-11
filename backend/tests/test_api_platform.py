"""Cross-service platform API: /api/v1/members/ and /api/v1/services/.
Neither is ITR-specific (a member is shared across every service; the
catalog lists all seven), so these stay out of tests/itr/."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from catalog.catalog import CATALOG
from itr.models import TaxFiler, TaxReturn

User = get_user_model()

_FILER_BODY = {
    'pan': 'abcde1234f', 'dob': '1990-01-01', 'email': 'm@example.com',
    'first_name': 'Gaurav', 'middle_name': '', 'last_name': 'Raut',
    'gender': 'M', 'father_name': 'X', 'mobile_number': '9999999999',
}


@override_settings(DEBUG=False)
class MembersApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='plat1', email='plat1@example.com', password='x')
        self.other = User.objects.create_user(username='plat2', email='plat2@example.com', password='x')
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')

    def test_create_uppercases_pan(self):
        r = self.client.post('/api/v1/members/', data=json.dumps(_FILER_BODY), content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['pan'], 'ABCDE1234F')

    def test_list_is_owner_scoped(self):
        mine = TaxFiler.objects.create(owner=self.owner, pan='ABCDE1234F', first_name='A', last_name='B',
                                        dob='1990-01-01', email='a@example.com', gender='M', father_name='F',
                                        mobile_number='9999999999')
        TaxFiler.objects.create(owner=self.other, pan='ZZZZZ9999Z', first_name='O', last_name='X',
                                 dob='1990-01-01', email='o@example.com', gender='F', father_name='F',
                                 mobile_number='8888888888')
        r = self.client.get('/api/v1/members/')
        self.assertEqual(r.status_code, 200)
        ids = [row['id'] for row in r.json()['results']]
        self.assertEqual(ids, [str(mine.pk)])

    def test_patch_partial_update_keeps_other_fields(self):
        filer = TaxFiler.objects.create(owner=self.owner, **{**_FILER_BODY, 'pan': 'ABCDE1234F'})
        r = self.client.patch(f'/api/v1/members/{filer.pk}/', data=json.dumps({'last_name': 'Changed'}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['last_name'], 'Changed')
        self.assertEqual(body['first_name'], 'Gaurav')  # untouched field survives the merge

    def test_delete_blocked_when_a_return_exists_for_the_pan(self):
        filer = TaxFiler.objects.create(owner=self.owner, **{**_FILER_BODY, 'pan': 'ABCDE1234F'})
        TaxReturn.objects.create(owner=self.owner, pan='ABCDE1234F')
        r = self.client.delete(f'/api/v1/members/{filer.pk}/')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(TaxFiler.objects.filter(pk=filer.pk).exists())

    def test_delete_succeeds_when_no_return_exists(self):
        filer = TaxFiler.objects.create(owner=self.owner, **{**_FILER_BODY, 'pan': 'ABCDE1234F'})
        r = self.client.delete(f'/api/v1/members/{filer.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(TaxFiler.objects.filter(pk=filer.pk).exists())

    def test_detail_404_for_non_owner(self):
        filer = TaxFiler.objects.create(owner=self.other, **{**_FILER_BODY, 'pan': 'ABCDE1234F'})
        r = self.client.get(f'/api/v1/members/{filer.pk}/')
        self.assertEqual(r.status_code, 404)

    def test_401_or_403_unauthenticated(self):
        self.client.logout()
        r = self.client.get('/api/v1/members/')
        self.assertIn(r.status_code, (401, 403))


@override_settings(DEBUG=False)
class ServicesApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='plat3', email='plat3@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_lists_all_seven_services(self):
        r = self.client.get('/api/v1/services/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['services']), 7)

    def test_status_is_a_machine_enum_not_display_text(self):
        r = self.client.get('/api/v1/services/')
        for s in r.json()['services']:
            self.assertIn(s['status'], ('available', 'coming_soon'))

    def test_itr_has_api_base_others_do_not(self):
        r = self.client.get('/api/v1/services/')
        by_slug = {s['slug']: s for s in r.json()['services']}
        self.assertEqual(by_slug['itr']['api_base'], '/api/v1/itr/')
        self.assertIsNone(by_slug['tds']['api_base'])

    def test_catalog_parity_with_web_dashboard(self):
        # One source of truth: catalog/catalog.py. If this ever fails, a
        # second hardcoded list crept in somewhere.
        api_slugs = [s['slug'] for s in self.client.get('/api/v1/services/').json()['services']]
        web_slugs = [s.slug for s in CATALOG]
        self.assertEqual(api_slugs, web_slugs)

        dashboard = self.client.get('/dashboard/')
        self.assertEqual(dashboard.status_code, 200)
        dashboard_slugs = [card['service'].slug for card in dashboard.context['cards']]
        self.assertEqual(dashboard_slugs, api_slugs)

    def test_401_or_403_unauthenticated(self):
        self.client.logout()
        r = self.client.get('/api/v1/services/')
        self.assertIn(r.status_code, (401, 403))
