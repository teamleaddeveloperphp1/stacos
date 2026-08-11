from captcha.models import CaptchaStore
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

User = get_user_model()


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='u@example.com', email='u@example.com', password='correct-horse-battery')

    def test_correct_password_no_mfa_lands_on_dashboard(self):
        response = self.client.post(reverse('accounts:login'), {'email': 'u@example.com', 'password': 'correct-horse-battery'})
        self.assertRedirects(response, reverse('catalog:dashboard'))
        self.assertTrue('_auth_user_id' in self.client.session)

    def test_correct_password_with_mfa_lands_on_verify_not_dashboard(self):
        device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        response = self.client.post(reverse('accounts:login'), {'email': 'u@example.com', 'password': 'correct-horse-battery'})
        self.assertRedirects(response, reverse('accounts:mfa_verify'))
        # not logged in yet -- MFA still pending
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session.get('pending_mfa_user_id'), self.user.pk)

    def test_wrong_password_does_not_reveal_account_existence(self):
        response = self.client.post(reverse('accounts:login'), {'email': 'u@example.com', 'password': 'nope'})
        self.assertContains(response, 'Incorrect email or password.')
        response2 = self.client.post(reverse('accounts:login'), {'email': 'nobody@example.com', 'password': 'nope'})
        self.assertContains(response2, 'Incorrect email or password.')

    def test_captcha_appears_after_three_failures(self):
        url = reverse('accounts:login')
        get_before = self.client.get(url)
        self.assertNotContains(get_before, 'class="captcha"')
        for _i in range(3):
            self.client.post(url, {'email': 'u@example.com', 'password': 'nope'})
        get_after = self.client.get(url)
        self.assertContains(get_after, 'class="captcha"')

    def test_successful_login_resets_failure_counter(self):
        url = reverse('accounts:login')
        self.client.post(url, {'email': 'u@example.com', 'password': 'nope'})
        self.client.post(url, {'email': 'u@example.com', 'password': 'nope'})
        self.client.post(url, {'email': 'u@example.com', 'password': 'correct-horse-battery'})
        get_after = self.client.get(url)
        self.assertNotContains(get_after, 'class="captcha"')

    def test_lockout_after_five_failures(self):
        # Past the 3rd failure our own UI starts requiring a captcha too --
        # supply a valid one so the form reaches authenticate() each time,
        # same as a real (if unlucky) user would.
        url = reverse('accounts:login')
        for _i in range(5):
            store = CaptchaStore.objects.create(challenge='ABCDEF', response='abcdef')
            self.client.post(url, {
                'email': 'u@example.com', 'password': 'nope',
                'captcha_0': store.hashkey, 'captcha_1': 'abcdef',
            })
        # Show-captcha is now active too -- include one so this request
        # actually reaches authenticate() (and therefore axes) instead of
        # failing form validation before axes ever sees it.
        store = CaptchaStore.objects.create(challenge='ABCDEF', response='abcdef')
        response = self.client.post(url, {
            'email': 'u@example.com', 'password': 'correct-horse-battery',
            'captcha_0': store.hashkey, 'captcha_1': 'abcdef',
        })
        # django-axes' default lockout response is 429 Too Many Requests.
        self.assertEqual(response.status_code, 429)


class LogoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='u2@example.com', email='u2@example.com', password='x')

    def test_logout_is_post_only(self):
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 405)

    def test_logout_flushes_session(self):
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')
        self.assertIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
