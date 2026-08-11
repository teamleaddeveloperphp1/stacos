from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Profile, get_profile

User = get_user_model()


class ProfileTests(TestCase):
    def test_get_profile_creates_if_missing(self):
        user = User.objects.create_user(username='a@example.com', email='a@example.com', password='x')
        self.assertFalse(Profile.objects.filter(user=user).exists())
        profile = get_profile(user)
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertFalse(profile.mfa_enforced)

    def test_get_profile_is_idempotent(self):
        user = User.objects.create_user(username='b@example.com', email='b@example.com', password='x')
        p1 = get_profile(user)
        p2 = get_profile(user)
        self.assertEqual(p1.pk, p2.pk)
