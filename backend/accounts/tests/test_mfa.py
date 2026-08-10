import time

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.mfa import base32_secret, generate_backup_codes
from accounts.models import MfaEnrollment, Profile

User = get_user_model()


class MfaSetupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='m@example.com', email='m@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def _totp_for_device(self, device):
        return pyotp.TOTP(base32_secret(device))

    def test_get_creates_unconfirmed_device(self):
        response = self.client.get(reverse('accounts:mfa_setup'))
        self.assertEqual(response.status_code, 200)
        device = TOTPDevice.objects.get(user=self.user, name='default')
        self.assertFalse(device.confirmed)

    def test_valid_code_confirms_device_and_shows_backup_codes(self):
        self.client.get(reverse('accounts:mfa_setup'))
        device = TOTPDevice.objects.get(user=self.user, name='default')
        code = self._totp_for_device(device).now()

        response = self.client.post(reverse('accounts:mfa_setup'), {'code': code})
        self.assertRedirects(response, reverse('accounts:mfa_backup_codes'))

        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertTrue(Profile.objects.get(user=self.user).mfa_enforced)
        self.assertIsNotNone(MfaEnrollment.objects.get(user=self.user).confirmed_at)

    def test_after_enabling_mfa_the_session_is_already_verified(self):
        # Regression: confirming setup used to leave mfa_enforced=True but
        # the session unverified, so AccessControlMiddleware bounced the
        # very next request to mfa/verify -- which then bounced again to
        # login, since there was never a pending-login state to check.
        self.client.get(reverse('accounts:mfa_setup'))
        device = TOTPDevice.objects.get(user=self.user, name='default')
        code = self._totp_for_device(device).now()
        self.client.post(reverse('accounts:mfa_setup'), {'code': code})

        response = self.client.post(reverse('accounts:mfa_backup_codes'), {'confirmed_saved': 'on'})
        self.assertRedirects(response, reverse('services:dashboard'))

        dashboard = self.client.get(reverse('services:dashboard'))
        self.assertEqual(dashboard.status_code, 200)

    def test_invalid_code_does_not_confirm(self):
        self.client.get(reverse('accounts:mfa_setup'))
        response = self.client.post(reverse('accounts:mfa_setup'), {'code': '000000'})
        self.assertEqual(response.status_code, 200)
        device = TOTPDevice.objects.get(user=self.user, name='default')
        self.assertFalse(device.confirmed)

    def test_replayed_code_is_rejected(self):
        self.client.get(reverse('accounts:mfa_setup'))
        device = TOTPDevice.objects.get(user=self.user, name='default')
        code = self._totp_for_device(device).now()
        device.verify_token(code)  # first use, outside the view
        self.assertFalse(device.verify_token(code))  # replay

    def test_code_from_adjacent_step_accepted(self):
        self.client.get(reverse('accounts:mfa_setup'))
        device = TOTPDevice.objects.get(user=self.user, name='default')
        totp = self._totp_for_device(device)
        drifted_code = totp.at(time.time() - 30)  # one 30s step in the past
        self.assertTrue(device.verify_token(drifted_code))

    def test_five_wrong_codes_regenerates_device(self):
        self.client.get(reverse('accounts:mfa_setup'))
        device = TOTPDevice.objects.get(user=self.user, name='default')
        for _i in range(5):
            self.client.post(reverse('accounts:mfa_setup'), {'code': '000000'})
        self.assertFalse(TOTPDevice.objects.filter(pk=device.pk).exists())


class BackupCodeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='b@example.com', email='b@example.com', password='x')

    def test_backup_code_works_once_and_only_once(self):
        codes = generate_backup_codes(self.user)
        device = StaticDevice.objects.get(user=self.user, name='backup')
        first = device.token_set.first().token
        self.assertTrue(device.verify_token(first))
        self.assertFalse(device.verify_token(first))
        self.assertEqual(len(codes), 10)

    def test_regeneration_invalidates_old_codes(self):
        first_batch = generate_backup_codes(self.user)
        second_batch = generate_backup_codes(self.user)
        device = StaticDevice.objects.get(user=self.user, name='backup')
        self.assertFalse(device.verify_token(first_batch[0]))
        self.assertTrue(device.verify_token(second_batch[0]))


class MfaLoginIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='l@example.com', email='l@example.com', password='correct-horse-battery')
        self.device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

    def _login_to_pending(self):
        return self.client.post(reverse('accounts:login'), {'email': 'l@example.com', 'password': 'correct-horse-battery'})

    def test_verify_with_totp_completes_login(self):
        self._login_to_pending()
        code = pyotp.TOTP(base32_secret(self.device)).now()
        response = self.client.post(reverse('accounts:mfa_verify'), {'code': code})
        self.assertRedirects(response, reverse('services:dashboard'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_verify_marks_session_otp_verified_not_just_authenticated(self):
        # Regression: django_otp.login() is a no-op if called before
        # django.contrib.auth.login() sets request.user -- a session that's
        # merely authenticated but not OTP-verified gets bounced by
        # AccessControlMiddleware right back to mfa_verify.
        self._login_to_pending()
        code = pyotp.TOTP(base32_secret(self.device)).now()
        self.client.post(reverse('accounts:mfa_verify'), {'code': code})
        response = self.client.get(reverse('services:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_verify_with_backup_code_completes_login(self):
        codes = generate_backup_codes(self.user)
        self._login_to_pending()
        response = self.client.post(reverse('accounts:mfa_verify'), {'code': codes[0]})
        self.assertRedirects(response, reverse('services:dashboard'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_backup_code_cannot_be_reused_at_login(self):
        codes = generate_backup_codes(self.user)
        self._login_to_pending()
        self.client.post(reverse('accounts:mfa_verify'), {'code': codes[0]})
        self.client.logout()

        self._login_to_pending()
        response = self.client.post(reverse('accounts:mfa_verify'), {'code': codes[0]})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_five_failed_verify_attempts_clears_pending_and_bounces_to_login(self):
        self._login_to_pending()
        url = reverse('accounts:mfa_verify')
        for _i in range(4):
            self.client.post(url, {'code': '000000'})
        response = self.client.post(url, {'code': '000000'})
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('pending_mfa_user_id', self.client.session)

    def test_verify_page_unreachable_without_pending_login(self):
        response = self.client.get(reverse('accounts:mfa_verify'))
        self.assertRedirects(response, reverse('accounts:login'))
