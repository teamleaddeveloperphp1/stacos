from captcha.fields import CaptchaField
from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class SignUpForm(forms.Form):
    """Minimal signup: username, email, password, confirm, captcha. Personal
    details and security questions come later, on request."""

    username = forms.CharField(label=_('Username'), max_length=150)
    email = forms.EmailField(label=_('Email'), max_length=254)
    password = forms.CharField(label=_('Password'), widget=forms.PasswordInput, min_length=10)
    confirm_password = forms.CharField(label=_('Confirm password'), widget=forms.PasswordInput)
    captcha = CaptchaField(label=_('Captcha'))

    def clean_username(self):
        # Usernames are display-only here (login is by email) and are
        # deliberately allowed to duplicate across accounts -- see
        # accounts.views.SignUpView.form_valid for how a collision with
        # Django's own unique auth_user.username column gets silently
        # disambiguated without ever surfacing to the user.
        return self.cleaned_data['username'].strip()

    def clean_email(self):
        # §4.4: unique, case-insensitive.
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_('An account with this email already exists.'))
        return email

    def clean_password(self):
        password = self.cleaned_data['password']
        password_validation.validate_password(password)
        return password

    def clean_confirm_password(self):
        confirm = self.cleaned_data.get('confirm_password')
        password = self.cleaned_data.get('password')
        if password and confirm and password != confirm:
            raise ValidationError(_("The passwords don't match."), code='password_mismatch')
        return confirm


class LoginForm(forms.Form):
    """§6.1: the captcha field only appears once the caller (the view, based
    on a per-IP failure counter) decides to show it -- a first-time user
    never sees one."""

    email = forms.EmailField(label=_('Email'))
    password = forms.CharField(label=_('Password'), widget=forms.PasswordInput)
    remember_me = forms.BooleanField(label=_('Remember me'), required=False)

    def __init__(self, *args, show_captcha=False, **kwargs):
        super().__init__(*args, **kwargs)
        if show_captcha:
            self.fields['captcha'] = CaptchaField(label=_('Captcha'))


class MfaSetupCodeForm(forms.Form):
    code = forms.CharField(
        label=_('6-digit code'), max_length=6, min_length=6,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code', 'maxlength': 6}),
    )


class MfaVerifyForm(forms.Form):
    """§5.3: the 6-digit TOTP code from the user's authenticator app."""

    code = forms.CharField(
        label=_('Code'),
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code'}),
    )


class ProfileForm(forms.Form):
    """§7.1. Email change requires the current password; username never
    changes silently either (both are login-relevant), but only email is
    spec'd as needing re-auth -- keep that distinction rather than
    demanding a password for every profile save."""

    username = forms.CharField(label=_('Username'), max_length=150)
    email = forms.EmailField(label=_('Email'), max_length=254)
    current_password = forms.CharField(
        label=_('Current password'), widget=forms.PasswordInput, required=False,
        help_text=_('Required only if you change your email.'),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        # Display-only, duplicates allowed -- see SignUpForm.clean_username.
        return self.cleaned_data['username'].strip()

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError(_('An account with this email already exists.'))
        return email

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        if email and self.user and email.lower() != self.user.email.lower():
            if not cleaned.get('current_password'):
                self.add_error('current_password', _('Enter your current password to change your email.'))
            elif not self.user.check_password(cleaned['current_password']):
                self.add_error('current_password', _('Incorrect password.'))
        return cleaned


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(label=_('Current password'), widget=forms.PasswordInput)
    new_password = forms.CharField(label=_('New password'), widget=forms.PasswordInput, min_length=10)
    confirm_new_password = forms.CharField(label=_('Confirm new password'), widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        password = self.cleaned_data['current_password']
        if not self.user.check_password(password):
            raise ValidationError(_('Incorrect password.'))
        return password

    def clean_new_password(self):
        password = self.cleaned_data['new_password']
        password_validation.validate_password(password, self.user)
        return password

    def clean_confirm_new_password(self):
        confirm = self.cleaned_data.get('confirm_new_password')
        password = self.cleaned_data.get('new_password')
        if password and confirm and password != confirm:
            raise ValidationError(_("The passwords don't match."), code='password_mismatch')
        return confirm


class LanguageForm(forms.Form):
    preferred_language = forms.ChoiceField(
        label=_('Language'), choices=[('en', 'English'), ('hi', 'हिन्दी')], widget=forms.RadioSelect,
    )


class MfaDisableForm(forms.Form):
    current_password = forms.CharField(label=_('Current password'), widget=forms.PasswordInput)
    code = forms.CharField(label=_('Current code'))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        password = self.cleaned_data['current_password']
        if not self.user.check_password(password):
            raise ValidationError(_('Incorrect password.'))
        return password


class DeleteAccountForm(forms.Form):
    """Confirms via email, not username -- usernames can be silently
    disambiguated behind the scenes on signup (duplicates are allowed), so
    the value actually stored may not match what the user remembers
    typing. Email is unique and always exactly what they know."""

    current_password = forms.CharField(label=_('Current password'), widget=forms.PasswordInput)
    confirm_email = forms.CharField(
        label=_('Type your email to confirm'),
        help_text=_('This deletes your account and every return you own. This cannot be undone.'),
    )
    code = forms.CharField(label=_('Current code'), required=False)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        password = self.cleaned_data['current_password']
        if not self.user.check_password(password):
            raise ValidationError(_('Incorrect password.'))
        return password

    def clean_confirm_email(self):
        value = self.cleaned_data['confirm_email'].strip().lower()
        if value != self.user.email.lower():
            raise ValidationError(_('Type your email exactly to confirm.'))
        return value
