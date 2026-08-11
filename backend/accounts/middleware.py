from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings

from accounts.models import get_profile

# §5.4 / §8.6: paths reachable without being logged in at all.
ALWAYS_ALLOWED_PREFIXES = (
    '/accounts/login/',
    '/accounts/logout/',
    '/accounts/signup/',
    '/accounts/mfa/verify/',
    '/accounts/forgot-password/',
    '/accounts/captcha/',
    '/static/',
    '/media/',
    '/healthz/',
    '/admin/',
)

# Reachable once logged in but before MFA enrollment/verification is done --
# a user must be able to reach these to ever finish enrolling.
MFA_SETUP_EXEMPT_PREFIXES = (
    '/accounts/mfa/setup/',
    '/accounts/mfa/qr',
)


def _is_exempt(path, prefixes):
    return any(path.startswith(p) for p in prefixes)


class AccessControlMiddleware:
    """Single allowlist-driven gate for both "must be logged in" (§8.6) and
    "must have completed MFA" (§5.4), so the seven existing itr views (and
    every future services/settings view) don't each need their own
    decorator. Per-object ownership (a return belongs to its owner) is
    handled separately, in the view's queryset -- this middleware only
    proves *who* is asking, not *what* they may see."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if _is_exempt(path, ALWAYS_ALLOWED_PREFIXES):
            return self.get_response(request)

        if not request.user.is_authenticated:
            login_url = reverse('accounts:login')
            return redirect(f'{login_url}?next={path}')

        if _is_exempt(path, MFA_SETUP_EXEMPT_PREFIXES):
            return self.get_response(request)

        profile = get_profile(request.user)

        if settings.MFA_REQUIRED and not profile.mfa_enforced:
            return redirect('accounts:mfa_setup')

        is_verified = getattr(request.user, 'is_verified', lambda: False)
        if profile.mfa_enforced and not is_verified():
            return redirect('accounts:mfa_verify')

        return self.get_response(request)
