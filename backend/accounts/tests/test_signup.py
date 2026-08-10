from captcha.models import CaptchaStore
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import AuthEvent

User = get_user_model()


class SignUpTests(TestCase):
    """Each test creates a real CaptchaStore row and submits its hashkey +
    response directly -- CAPTCHA_TEST_MODE can't be used here since
    django-simple-captcha reads it into a module-level constant at import
    time, before override_settings can patch it."""

    def setUp(self):
        cache.clear()

    def _fresh_captcha(self, response='abcdef'):
        store = CaptchaStore.objects.create(challenge=response.upper(), response=response)
        return store.hashkey

    def _payload(self, captcha_response='abcdef', **overrides):
        payload = {
            'username': 'asha',
            'email': 'asha@example.com',
            'password': 'correct-horse-battery',
            'confirm_password': 'correct-horse-battery',
            'captcha_0': self._fresh_captcha(captcha_response),
            'captcha_1': captcha_response,
        }
        payload.update(overrides)
        return payload

    def test_happy_path_creates_user(self):
        response = self.client.post(reverse('accounts:signup'), self._payload())
        self.assertRedirects(response, reverse('accounts:mfa_setup'))

        user = User.objects.get(email='asha@example.com')
        self.assertEqual(user.username, 'asha')
        self.assertTrue(user.check_password('correct-horse-battery'))
        self.assertTrue(AuthEvent.objects.filter(user=user, event='signup').exists())

    def test_duplicate_username_is_allowed_and_disambiguated(self):
        User.objects.create_user(username='asha', email='other@example.com', password='x')
        response = self.client.post(reverse('accounts:signup'), self._payload())
        self.assertRedirects(response, reverse('accounts:mfa_setup'))
        new_user = User.objects.get(email='asha@example.com')
        self.assertTrue(new_user.username.startswith('asha-'))
        self.assertNotEqual(new_user.username, 'asha')

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username='existing', email='asha@example.com', password='x')
        response = self.client.post(reverse('accounts:signup'), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(User.objects.filter(email='asha@example.com').count(), 1)

    def test_mismatched_passwords_rejected(self):
        response = self.client.post(reverse('accounts:signup'), self._payload(confirm_password='different'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='asha@example.com').exists())

    def test_wrong_captcha_rejected(self):
        payload = self._payload()
        payload['captcha_1'] = 'wrong'
        response = self.client.post(reverse('accounts:signup'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='asha@example.com').exists())

    def test_correct_captcha_different_case_accepted(self):
        payload = self._payload()
        payload['captcha_1'] = payload['captcha_1'].upper()
        response = self.client.post(reverse('accounts:signup'), payload)
        self.assertRedirects(response, reverse('accounts:mfa_setup'))
        self.assertTrue(User.objects.filter(email='asha@example.com').exists())

    def test_form_rerenders_preserving_non_sensitive_values_on_error(self):
        response = self.client.post(reverse('accounts:signup'), self._payload(confirm_password='different'))
        self.assertContains(response, 'asha@example.com')

    def test_signup_rate_limited_per_ip(self):
        url = reverse('accounts:signup')
        for i in range(10):
            self.client.post(url, self._payload(username=f'user{i}', email=f'user{i}@example.com'))
        response = self.client.post(url, self._payload(username='overflow', email='overflow@example.com'))
        self.assertContains(response, 'Too many signup attempts')
        self.assertFalse(User.objects.filter(email='overflow@example.com').exists())
