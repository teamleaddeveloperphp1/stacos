import uuid

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Extends the stock `django.contrib.auth.User` (its migrations are
    already applied against a real DB, so we attach a profile rather than
    swapping AUTH_USER_MODEL). `email` for login lives on
    the built-in User.email field; uniqueness is enforced at the form layer
    (accounts.forms.SignUpForm), not a DB constraint on a table we don't own.
    """

    LANGUAGE_CHOICES = [('en', 'English'), ('hi', 'हिन्दी')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    middle_name = models.CharField(max_length=150, blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=10, blank=True, unique=False)
    date_of_birth = models.DateField(null=True, blank=True)
    preferred_language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='en')
    mfa_enforced = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True)
    terms_accepted_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f'Profile<{self.user_id}>'


def get_profile(user):
    """The one place that assumes a Profile exists -- every view can call
    this instead of scattering `hasattr`/null-checks (mirrors how itr's
    `_current_user` used to be the single seam for user lookup)."""
    profile, _created = Profile.objects.get_or_create(user=user)
    return profile


class MfaEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'MfaEnrollment<{self.user_id}>'


class AuthEvent(models.Model):
    EVENT_CHOICES = [
        ('signup', 'signup'),
        ('login_ok', 'login_ok'),
        ('login_fail', 'login_fail'),
        ('mfa_ok', 'mfa_ok'),
        ('mfa_fail', 'mfa_fail'),
        ('mfa_enabled', 'mfa_enabled'),
        ('mfa_disabled', 'mfa_disabled'),
        ('logout', 'logout'),
        ('pwd_reset_start', 'pwd_reset_start'),
        ('pwd_reset_ok', 'pwd_reset_ok'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='auth_events')
    email_attempted = models.CharField(max_length=254, blank=True)
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event} @ {self.created_at:%Y-%m-%d %H:%M} ({self.user_id or self.email_attempted})'


def log_auth_event(request, event, user=None, email_attempted=''):
    """Single write path for AuthEvent so no call site forgets ip/UA, and so
    it's obvious at a glance that nothing sensitive (password, TOTP code,
    security answer, captcha value) is ever passed in here."""
    AuthEvent.objects.create(
        user=user if (user and user.is_authenticated) else None,
        email_attempted=email_attempted,
        event=event,
        ip=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
    )
