import pyotp
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.mfa import base32_secret
from accounts.models import Profile

User = get_user_model()


class SettingsAccessTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse('accounts:settings'))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:settings')}")


class ProfileSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s1', email='s1@example.com', password='correct-horse-battery')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_username_change_saves_independently(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'profile', 'username': 's1-renamed', 'email': self.user.email,
        })
        self.assertRedirects(response, reverse('accounts:settings'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 's1-renamed')

    def test_email_change_requires_current_password(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'profile', 'username': self.user.username, 'email': 'new@example.com',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 's1@example.com')

    def test_email_change_with_correct_password_succeeds(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'profile', 'username': self.user.username, 'email': 'new@example.com',
            'current_password': 'correct-horse-battery',
        })
        self.assertRedirects(response, reverse('accounts:settings'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')


class PasswordSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s2', email='s2@example.com', password='correct-horse-battery')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_change_password_keeps_current_session_alive(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'password', 'current_password': 'correct-horse-battery',
            'new_password': 'new-correct-horse', 'confirm_new_password': 'new-correct-horse',
        })
        self.assertRedirects(response, reverse('accounts:settings'))
        self.assertIn('_auth_user_id', self.client.session)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-correct-horse'))

    def test_wrong_current_password_rejected(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'password', 'current_password': 'nope',
            'new_password': 'new-correct-horse', 'confirm_new_password': 'new-correct-horse',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('correct-horse-battery'))

    def test_password_change_invalidates_other_sessions(self):
        other_client = self.client.__class__()
        other_client.force_login(self.user, backend='accounts.backends.EmailBackend')
        self.assertIn('_auth_user_id', other_client.session)

        self.client.post(reverse('accounts:settings'), {
            'section': 'password', 'current_password': 'correct-horse-battery',
            'new_password': 'new-correct-horse', 'confirm_new_password': 'new-correct-horse',
        })

        other_client.cookies = other_client.cookies  # no-op, just re-request with same session cookie
        response = other_client.get(reverse('accounts:settings'))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:settings')}")


class MfaDisableTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s4', email='s4@example.com', password='correct-horse-battery')
        self.device = TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)
        profile = Profile.objects.create(user=self.user, mfa_enforced=True)
        self.profile = profile
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = self.device.persistent_id
        session.save()

    def test_disable_requires_password_and_code(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'mfa_disable', 'current_password': 'correct-horse-battery', 'code': '000000',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TOTPDevice.objects.filter(user=self.user, confirmed=True).exists())

    def test_disable_succeeds_with_valid_password_and_code(self):
        code = pyotp.TOTP(base32_secret(self.device)).now()
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'mfa_disable', 'current_password': 'correct-horse-battery', 'code': code,
        })
        self.assertRedirects(response, reverse('accounts:settings'))
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.mfa_enforced)


class DeleteAccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s5', email='s5@example.com', password='correct-horse-battery')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_delete_requires_correct_email_confirmation(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'delete_account', 'current_password': 'correct-horse-battery', 'confirm_email': 'wrong@example.com',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_succeeds_and_logs_out(self):
        response = self.client.post(reverse('accounts:settings'), {
            'section': 'delete_account', 'current_password': 'correct-horse-battery', 'confirm_email': 's5@example.com',
        })
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())


class SessionsSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='s6', email='s6@example.com', password='x')
        self.client.force_login(self.user, backend='accounts.backends.EmailBackend')

    def test_sign_out_everywhere_flushes_session(self):
        response = self.client.post(reverse('accounts:settings'), {'section': 'sessions'})
        self.assertRedirects(response, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
