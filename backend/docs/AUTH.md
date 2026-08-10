# Auth, MFA, and the services dashboard

## Status

Implemented: signup, login/logout, TOTP MFA (setup, login-time verify,
backup codes), a Settings page, the services dashboard + coming-soon
pages, and returns-flow access control.

**Not implemented (by explicit request, not an oversight):**
- Security questions at signup, and the 2-of-5-question password recovery
  flow (§6.3 of the original spec). Signup only collects
  username/email/password/confirm/captcha. `/accounts/forgot-password/`
  and its two follow-on URLs exist and resolve (200) but are still the
  Phase-1 placeholder page — there's no working recovery path yet.
- Hindi (`hi.json`) translations for anything added in this epic — new
  accounts/services copy is English-only for now, by request. The
  itr1 app's own pre-existing Hindi strings are untouched and still work.

## URL map

| URL | View | Notes |
|---|---|---|
| `/accounts/signup/` | `SignUpView` | username, email, password, confirm, captcha |
| `/accounts/login/` | `LoginView` | email + password; captcha appears after 3 failed attempts from the same IP; routes to MFA verify if the user has a confirmed device |
| `/accounts/logout/` | `LogoutView` | POST-only |
| `/accounts/mfa/setup/` | `MfaSetupView` | QR + manual secret + 6-digit code; reachable pre-MFA |
| `/accounts/mfa/verify/` | `MfaVerifyView` | login-time gate; TOTP or backup code, one field |
| `/accounts/mfa/backup-codes/` | `MfaBackupCodesView` | shows 10 codes once, then only a remaining-count |
| `/accounts/forgot-password/`, `.../verify/`, `.../reset/` | placeholders | not implemented, see above |
| `/accounts/settings/` | `SettingsView` | 6 independently-saving sections, POST discriminated by `section=` |
| `/accounts/captcha/...` | django-simple-captcha | mounted at the project level in `config/urls.py`, **not** nested inside `accounts.urls`'s `app_name` — its own `reverse("captcha-image", ...)` calls break otherwise |
| `/dashboard/` | `services.DashboardView` | `LOGIN_REDIRECT_URL`; 5 service cards from `services/catalog.py` |
| `/services/<slug>/` | `services.ServiceView` | always 200, unknown slug renders the same coming-soon template |
| `/returns/...` (itr1) | unchanged | now requires real login; ownership already enforced via `owner=` filter, 404 (not 403) on mismatch |
| `/healthz/` | `healthz` | always-allowed, plain 200 |

## Settings sections (what's there vs. the original 7-card spec)

Built: **Profile** (username/email, email change requires current
password), **Password** (invalidates other sessions,
`update_session_auth_hash` keeps the current one alive), **Two-factor
authentication** (status chip, set up / regenerate backup codes / disable
with password+code), **Language** (en/hi radio, applies immediately via
`request.session['locale']`), **Active sessions** (list + sign out
everywhere), **Danger zone** (typed-username confirmation + password +
MFA code if enabled, cascades to `Profile`/`TaxReturn`).

Not built: a **Security questions** card — there's nothing to manage
since signup doesn't collect them.

## Settings flags (env vars, all in `config/settings.py`)

| Setting | Default | Purpose |
|---|---|---|
| `MFA_REQUIRED` | `false` | If true, `AccessControlMiddleware` forces every user through `/accounts/mfa/setup/` before anything else. If false (default), MFA is offered but skippable. |
| `TERMS_URL` / `PRIVACY_URL` | `https://www.stacos.com/{terms,privacy}.php` | Unused now that signup dropped the terms checkbox; still read by `settings.py` if that comes back. |
| `TERMS_VERSION` | `2026-08` | Same — currently unused. |
| `OTP_TOTP_ISSUER` | `STACOS.ai` | Shown in the authenticator app next to the account. |
| `STRICT_ENUMERATION_DEFENCE` | `true` | Reserved for the recovery flow once it's built; unused today. |

## Adding a service to the dashboard

Edit `services/catalog.py::CATALOG` — one `Service(...)` entry per card.
`available=False` services automatically get the coming-soon page at
`/services/<slug>/` with **zero** other code changes; `available=True`
services need `url_name` set to a real, reversible URL name (see the
`tds-itr` entry, which points at `itr1:return_list`).

## Access control model

`accounts.middleware.AccessControlMiddleware` is a single allowlist-driven
gate (see the module docstring for the exact allow-lists) that handles
"must be logged in" and "must have completed MFA if enforced." It does
**not** handle per-object ownership — that's still each view's job (for
itr1, `itr1.views._get_return` filtering `TaxReturn.objects.filter(pk=...,
owner=user)`, which already existed before this epic and needed no
changes beyond removing the demo-user fallback in `_current_user`).

## Unlocking a locked-out user (django-axes) from the shell

```python
python manage.py shell
>>> from axes.models import AccessAttempt
>>> AccessAttempt.objects.filter(username='someone@example.com').delete()
```

Or from the command line: `python manage.py axes_reset_username someone@example.com`
(or `axes_reset` to clear every lockout).

## Resetting a user's MFA (lost device, no backup codes)

```python
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> from django_otp.plugins.otp_totp.models import TOTPDevice
>>> from django_otp.plugins.otp_static.models import StaticDevice
>>> from accounts.models import get_profile
>>> user = get_user_model().objects.get(email='someone@example.com')
>>> TOTPDevice.objects.filter(user=user).delete()
>>> StaticDevice.objects.filter(user=user).delete()
>>> profile = get_profile(user); profile.mfa_enforced = False; profile.save()
```

They'll be prompted to set up MFA again next time `/accounts/mfa/setup/`
is reached (immediately, if `MFA_REQUIRED=True`).
