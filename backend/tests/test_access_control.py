from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from itr1.models import TaxReturn

User = get_user_model()


class ReturnsAccessControlTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='x')
        self.other = User.objects.create_user(username='other', email='other@example.com', password='x')
        self.tax_return = TaxReturn.objects.create(owner=self.owner)

    def test_anonymous_redirected_to_login_with_next(self):
        url = reverse('itr1:personal_info', args=[self.tax_return.pk])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_owner_can_open_their_return(self):
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        response = self.client.get(reverse('itr1:personal_info', args=[self.tax_return.pk]))
        self.assertEqual(response.status_code, 200)

    def test_other_user_gets_404_not_403(self):
        self.client.force_login(self.other, backend='accounts.backends.EmailBackend')
        response = self.client.get(reverse('itr1:personal_info', args=[self.tax_return.pk]))
        self.assertEqual(response.status_code, 404)

    def test_new_return_is_owned_by_its_creator(self):
        self.client.force_login(self.other, backend='accounts.backends.EmailBackend')
        self.client.post(reverse('itr1:return_create'))
        created = TaxReturn.objects.exclude(pk=self.tax_return.pk).get(owner=self.other)
        self.assertEqual(created.owner, self.other)

    def test_return_list_only_shows_owners_returns(self):
        self.client.force_login(self.owner, backend='accounts.backends.EmailBackend')
        response = self.client.get(reverse('itr1:return_list'))
        pks = {card['obj'].pk for card in response.context['cards']}
        self.assertEqual(pks, {self.tax_return.pk})
