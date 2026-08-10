import uuid
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.sessions.models import Session
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.generic import FormView, TemplateView
import django_otp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.forms import (
    ChangePasswordForm,
    DeleteAccountForm,
    LanguageForm,
    LoginForm,
    MfaDisableForm,
    MfaSetupCodeForm,
    MfaVerifyForm,
    ProfileForm,
    SignUpForm,
)
from accounts.i18n_translate import translate
from accounts.mfa import base32_secret, find_verified_device, get_or_create_setup_device, qr_data_uri
from accounts.models import MfaEnrollment, get_profile, log_auth_event
from accounts.ratelimit import check_and_increment, get_counter, increment_counter, reset_counter

User = get_user_model()


def _disambiguated_username(desired, exclude_pk=None):
    """auth_user.username is unique at the DB level (Django core, not
    something this app can relax without forking django.contrib.auth) --
    but duplicate *display* usernames are allowed by design here (login is
    by email). Silently append a short suffix on collision so signup/
    profile-save never rejects a name someone else already picked."""
    qs = User.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if not qs.filter(username__iexact=desired).exists():
        return desired
    base = desired[:143]  # leave room for "-xxxxxx" within the 150-char column
    while True:
        candidate = f'{base}-{uuid.uuid4().hex[:6]}'
        if not qs.filter(username__iexact=candidate).exists():
            return candidate


CAPTCHA_AFTER_N_FAILURES = 3
PENDING_MFA_SESSION_KEY = 'pending_mfa_user_id'
PENDING_MFA_STARTED_KEY = 'pending_mfa_started_at'
PENDING_MFA_REMEMBER_KEY = 'pending_mfa_remember'
PENDING_MFA_NEXT_KEY = 'pending_mfa_next'
PENDING_MFA_FAIL_KEY = 'pending_mfa_fail_count'
PENDING_MFA_TTL_SECONDS = 5 * 60
MFA_MAX_ATTEMPTS = 5


class _PlaceholderView(TemplateView):
    """Phase 1 skeleton stub -- URL names are final, bodies are filled in by
    the phase noted below. Kept as a plain template so `manage.py check` and
    the middleware allowlist can be verified before any real behaviour
    exists."""

    template_name = 'accounts/_placeholder.html'
    phase_note = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['phase_note'] = self.phase_note
        return ctx


class SignUpView(FormView):
    template_name = 'accounts/signup.html'
    form_class = SignUpForm
    success_url = reverse_lazy('accounts:mfa_setup')

    def post(self, request, *args, **kwargs):
        # §11: signup rate-limited to 10/hour/IP.
        ip = request.META.get('REMOTE_ADDR', 'unknown')
        if not check_and_increment(f'signup:{ip}', limit=10, period_seconds=3600):
            form = self.get_form()
            form.add_error(None, _('Too many signup attempts from this network. Please try again later.'))
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # §6 quality floor: aria-invalid + aria-describedby pointing at the
        # error node the template renders right below each field.
        for name in ('username', 'email', 'password', 'confirm_password'):
            if form.errors.get(name):
                field = form.fields[name]
                field.widget.attrs['aria-invalid'] = 'true'
                field.widget.attrs['aria-describedby'] = f'id_{name}_error'
        return super().form_invalid(form)

    def form_valid(self, form):
        data = form.cleaned_data

        username = _disambiguated_username(data['username'])
        user = User(username=username, email=data['email'])
        user.set_password(data['password'])
        user.save()

        log_auth_event(self.request, 'signup', user=user)

        login(self.request, user, backend='accounts.backends.EmailBackend')

        messages.success(
            self.request,
            _('Account created. Set up two-factor authentication to secure your account.'),
        )
        return super().form_valid(form)


@method_decorator(csrf_protect, name='dispatch')
class LoginView(View):
    template_name = 'accounts/login.html'

    def _fail_key(self, request):
        return f'login_fails:{request.META.get("REMOTE_ADDR", "unknown")}'

    def _show_captcha(self, request):
        return get_counter(self._fail_key(request)) >= CAPTCHA_AFTER_N_FAILURES

    def _wire_aria(self, form):
        # §6 quality floor: aria-invalid + aria-describedby pointing at the
        # error node the template renders right below each field -- errors
        # must never rely on colour alone.
        for name in ('email', 'password'):
            if form.errors.get(name):
                field = form.fields[name]
                field.widget.attrs['aria-invalid'] = 'true'
                field.widget.attrs['aria-describedby'] = f'id_{name}_error'
        return form

    def get(self, request):
        form = LoginForm(show_captcha=self._show_captcha(request))
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        show_captcha = self._show_captcha(request)
        form = LoginForm(request.POST, show_captcha=show_captcha)

        if not form.is_valid():
            return render(request, self.template_name, {'form': self._wire_aria(form)})

        email = form.cleaned_data['email']
        password = form.cleaned_data['password']

        user = authenticate(request, username=email, password=password)

        if user is None:
            # §6.1: non-enumerating -- never reveals whether the account
            # exists. django-axes' own lockout (5/15min, 30min cooloff) is
            # enforced separately by AxesMiddleware on the response; this
            # counter only decides when to start showing a captcha.
            increment_counter(self._fail_key(request), period_seconds=3600)
            log_auth_event(request, 'login_fail', email_attempted=email)
            form = LoginForm(request.POST, show_captcha=self._show_captcha(request))
            form.add_error(None, _('Incorrect email or password.'))
            return render(request, self.template_name, {'form': form})

        reset_counter(self._fail_key(request))

        if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            # §5.3: MFA verification happens before django.contrib.auth.login()
            # completes -- the user is not authenticated yet.
            request.session[PENDING_MFA_SESSION_KEY] = user.pk
            request.session[PENDING_MFA_STARTED_KEY] = timezone.now().isoformat()
            request.session[PENDING_MFA_REMEMBER_KEY] = bool(form.cleaned_data.get('remember_me'))
            next_url = request.POST.get('next') or request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
                request.session[PENDING_MFA_NEXT_KEY] = next_url
            return redirect('accounts:mfa_verify')

        login(request, user, backend='accounts.backends.EmailBackend')
        if not form.cleaned_data.get('remember_me'):
            request.session.set_expiry(0)

        log_auth_event(request, 'login_ok', user=user)

        next_url = request.POST.get('next') or request.GET.get('next', '')
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
            return redirect(next_url)
        return redirect(settings.LOGIN_REDIRECT_URL)


@method_decorator(csrf_protect, name='dispatch')
class LogoutView(View):
    """§6.2: POST-only -- a GET logout link is triggerable by link
    prefetchers/crawlers, so it must never be reachable via GET."""

    def get(self, request):
        return HttpResponseNotAllowed(['POST'])

    def post(self, request):
        # django.contrib.auth.logout() flushes the whole session (including
        # pending-MFA keys and the locale choice), so read what we need first.
        locale = request.session.get('locale', 'en')
        user = request.user if request.user.is_authenticated else None
        logout(request)
        if user:
            log_auth_event(request, 'logout', user=user)
        request.session['locale'] = locale
        messages.info(request, translate(locale, 'signed_out_message'))
        return redirect('accounts:login')


@method_decorator(csrf_protect, name='dispatch')
class MfaSetupView(View):
    """§5.1. Reachable once logged in, before or after MFA is confirmed --
    the AccessControlMiddleware allowlist lets an unverified, freshly-signed-
    up user reach this even though every other page requires it."""

    template_name = 'accounts/mfa_setup.html'

    def _attempts_key(self, request):
        return f'mfa_setup_attempts:{request.user.pk}'

    def _render(self, request, device, form):
        response = render(request, self.template_name, {
            'form': form,
            'qr_data_uri': qr_data_uri(device.config_url),
            'secret': base32_secret(device),
            'skippable': not settings.MFA_REQUIRED,
        })
        response['Cache-Control'] = 'no-store'
        return response

    def get(self, request):
        if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
            return redirect('accounts:settings')
        device = get_or_create_setup_device(request.user)
        return self._render(request, device, MfaSetupCodeForm())

    def post(self, request):
        device = TOTPDevice.objects.filter(user=request.user, name='default', confirmed=False).first()
        if device is None:
            return redirect('accounts:mfa_setup')

        form = MfaSetupCodeForm(request.POST)
        if form.is_valid() and device.verify_token(form.cleaned_data['code']):
            device.confirmed = True
            device.save()

            # Mark *this* session OTP-verified immediately -- request.user
            # is already the real, logged-in user here (unlike the
            # login-time flow in MfaVerifyView, where auth.login() has to
            # run first), so there's no ordering hazard. Skipping this
            # left profile.mfa_enforced=True but the session unverified,
            # and AccessControlMiddleware would immediately bounce the
            # very next request to /accounts/mfa/verify/ -- which then
            # finds no pending-login state and bounces again to login,
            # looking like signup "doesn't work".
            django_otp.login(request, device)

            profile = get_profile(request.user)
            profile.mfa_enforced = True
            profile.save()

            enrollment, _created = MfaEnrollment.objects.get_or_create(user=request.user)
            enrollment.confirmed_at = timezone.now()
            enrollment.save()

            log_auth_event(request, 'mfa_enabled', user=request.user)

            messages.success(request, _('Two-factor authentication is now enabled.'))
            return redirect(settings.LOGIN_REDIRECT_URL)

        attempts = increment_counter(self._attempts_key(request), period_seconds=3600)
        if attempts >= MFA_MAX_ATTEMPTS:
            device.delete()
            reset_counter(self._attempts_key(request))
            messages.error(request, _('Too many attempts — scan the new QR code below.'))
            return redirect('accounts:mfa_setup')

        if not form.is_valid():
            return self._render(request, device, form)
        form.add_error(None, _("That code isn't right. Check your authenticator app and try again."))
        return self._render(request, device, form)


@method_decorator(csrf_protect, name='dispatch')
class MfaVerifyView(View):
    """§5.3: reached after a correct password when the user has a confirmed
    TOTP device -- django.contrib.auth login is *not* complete yet."""

    template_name = 'accounts/mfa_verify.html'

    def _pending_user(self, request):
        user_id = request.session.get(PENDING_MFA_SESSION_KEY)
        started = request.session.get(PENDING_MFA_STARTED_KEY)
        if not user_id or not started:
            return None
        age = timezone.now() - datetime.fromisoformat(started)
        if age.total_seconds() > PENDING_MFA_TTL_SECONDS:
            return None
        return User.objects.filter(pk=user_id).first()

    def _clear_pending(self, request):
        for key in (PENDING_MFA_SESSION_KEY, PENDING_MFA_STARTED_KEY, PENDING_MFA_REMEMBER_KEY,
                    PENDING_MFA_NEXT_KEY, PENDING_MFA_FAIL_KEY):
            request.session.pop(key, None)

    def get(self, request):
        if self._pending_user(request) is None:
            self._clear_pending(request)
            messages.error(request, _('Your sign-in session expired. Please sign in again.'))
            return redirect('accounts:login')
        return render(request, self.template_name, {'form': MfaVerifyForm()})

    def post(self, request):
        user = self._pending_user(request)
        if user is None:
            self._clear_pending(request)
            messages.error(request, _('Your sign-in session expired. Please sign in again.'))
            return redirect('accounts:login')

        form = MfaVerifyForm(request.POST)
        device = find_verified_device(user, form.cleaned_data['code']) if form.is_valid() else None
        if device is not None:
            remember = request.session.get(PENDING_MFA_REMEMBER_KEY, False)
            next_url = request.session.get(PENDING_MFA_NEXT_KEY, '')
            self._clear_pending(request)

            # django.contrib.auth.login() must run before django_otp.login()
            # -- the latter is a no-op until request.user is the real user.
            login(request, user, backend='accounts.backends.EmailBackend')
            django_otp.login(request, device)
            if not remember:
                request.session.set_expiry(0)

            log_auth_event(request, 'mfa_ok', user=user)

            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)

        fail_count = request.session.get(PENDING_MFA_FAIL_KEY, 0) + 1
        log_auth_event(request, 'mfa_fail', user=user)
        if fail_count >= MFA_MAX_ATTEMPTS:
            self._clear_pending(request)
            messages.error(request, _('Too many incorrect codes. Please sign in again.'))
            return redirect('accounts:login')

        request.session[PENDING_MFA_FAIL_KEY] = fail_count
        if not form.errors.get('code'):
            form.add_error(None, _("That code isn't right. Try again."))
        return render(request, self.template_name, {'form': form})


class ForgotPasswordIdentifyView(_PlaceholderView):
    phase_note = 'Phase 6 — Password recovery (step 1)'


class ForgotPasswordVerifyView(_PlaceholderView):
    phase_note = 'Phase 6 — Password recovery (step 2)'


class ForgotPasswordResetView(_PlaceholderView):
    phase_note = 'Phase 6 — Password recovery (step 3)'


def _user_sessions(user):
    """No dedicated session/device-tracking model exists (out of scope for
    this pass) -- Session.get_decoded() is the only way to find which
    sessions belong to this user without one."""
    sessions = []
    for s in Session.objects.filter(expire_date__gte=timezone.now()):
        if s.get_decoded().get('_auth_user_id') == str(user.pk):
            sessions.append(s)
    return sessions


@method_decorator(csrf_protect, name='dispatch')
class SettingsView(View):
    """§7: one page, independently-saving fieldset-cards, dispatched by a
    `section=` POST discriminator so every card can share one URL. Security
    questions are intentionally not a section here -- signup doesn't
    collect them (see accounts/forms.py::SignUpForm), so there's nothing to
    manage yet."""

    template_name = 'accounts/settings.html'

    def _context(self, request, **extra):
        user = request.user
        profile = get_profile(user)
        mfa_device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        ctx = {
            'profile_form': ProfileForm(user=user, initial={'username': user.username, 'email': user.email}),
            'password_form': ChangePasswordForm(user=user),
            'language_form': LanguageForm(initial={'preferred_language': profile.preferred_language}),
            'mfa_disable_form': MfaDisableForm(user=user),
            'delete_form': DeleteAccountForm(user=user),
            'mfa_enabled': mfa_device is not None,
            'sessions': _user_sessions(user),
            'current_session_key': request.session.session_key,
        }
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, self.template_name, self._context(request))

    def post(self, request):
        section = request.POST.get('section')
        handler = getattr(self, f'_post_{section}', None)
        if handler is None:
            return redirect('accounts:settings')
        return handler(request)

    def _post_profile(self, request):
        user = request.user
        form = ProfileForm(request.POST, user=user)
        if not form.is_valid():
            return render(request, self.template_name, self._context(request, profile_form=form))
        user.username = _disambiguated_username(form.cleaned_data['username'], exclude_pk=user.pk)
        user.email = form.cleaned_data['email']
        user.save()
        messages.success(request, _('Profile updated.'))
        return redirect('accounts:settings')

    def _post_password(self, request):
        user = request.user
        form = ChangePasswordForm(request.POST, user=user)
        if not form.is_valid():
            return render(request, self.template_name, self._context(request, password_form=form))
        user.set_password(form.cleaned_data['new_password'])
        user.save()
        update_session_auth_hash(request, user)  # keep this session alive
        for s in _user_sessions(user):
            if s.session_key != request.session.session_key:
                s.delete()
        messages.success(request, _('Password changed. Other sessions were signed out.'))
        return redirect('accounts:settings')

    def _post_language(self, request):
        form = LanguageForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(request, language_form=form))
        profile = get_profile(request.user)
        profile.preferred_language = form.cleaned_data['preferred_language']
        profile.save()
        request.session['locale'] = profile.preferred_language
        messages.success(request, _('Language updated.'))
        return redirect('accounts:settings')

    def _post_mfa_disable(self, request):
        user = request.user
        form = MfaDisableForm(request.POST, user=user)
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if form.is_valid():
            if device is None or find_verified_device(user, form.cleaned_data['code']) is None:
                form.add_error('code', _("That code isn't right."))
        if not form.is_valid():
            return render(request, self.template_name, self._context(request, mfa_disable_form=form))
        TOTPDevice.objects.filter(user=user).delete()
        profile = get_profile(user)
        profile.mfa_enforced = False
        profile.save()
        log_auth_event(request, 'mfa_disabled', user=user)
        messages.success(request, _('Two-factor authentication disabled.'))
        return redirect('accounts:settings')

    def _post_sessions(self, request):
        for s in _user_sessions(request.user):
            s.delete()
        logout(request)
        messages.info(request, _('You have been signed out everywhere.'))
        return redirect('accounts:login')

    def _post_delete_account(self, request):
        user = request.user
        profile = get_profile(user)
        form = DeleteAccountForm(request.POST, user=user)
        if form.is_valid() and profile.mfa_enforced:
            if find_verified_device(user, form.cleaned_data.get('code', '')) is None:
                form.add_error('code', _("That code isn't right."))
        if not form.is_valid():
            return render(request, self.template_name, self._context(request, delete_form=form))
        logout(request)
        user.delete()  # cascades to Profile, TaxReturn (owner FK)
        messages.info(request, _('Your account has been deleted.'))
        return redirect('accounts:login')
