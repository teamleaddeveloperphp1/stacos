from accounts.i18n_translate import translate as _translate_accounts
from itr.i18n_translate import translate as _translate_itr
from services.i18n_translate import translate as _translate_services

# Checked in this order for every `{{ t.some_key }}` lookup site-wide, first
# non-fallback hit wins -- lets accounts/services/itr templates share one
# `t` context variable and one `{{ t.key }}` convention (see each app's
# i18n_translate.py docstring for why this isn't Django gettext).
_TRANSLATORS = (_translate_accounts, _translate_services, _translate_itr)


class _Translator(dict):
    """Lets templates write `{{ t.some_key }}` for any key in any bundle --
    Django's template dot-lookup tries dict `__getitem__` first, and
    `__missing__` resolves keys lazily rather than requiring every key to be
    pre-populated."""

    def __init__(self, locale):
        super().__init__()
        self.locale = locale

    def __missing__(self, key):
        for translate in _TRANSLATORS:
            value = translate(self.locale, key)
            if value != key:
                return value
        return key


def i18n(request):
    locale = request.session.get('locale', 'en')
    return {'t': _Translator(locale), 'current_locale': locale}
