from itr1.i18n_translate import translate


class _Translator(dict):
    """Lets templates write `{{ t.some_key }}` for any key in the bundle --
    Django's template dot-lookup tries dict `__getitem__` first, and
    `__missing__` resolves keys lazily rather than requiring every key to be
    pre-populated."""

    def __init__(self, locale):
        super().__init__()
        self.locale = locale

    def __missing__(self, key):
        return translate(self.locale, key)


def i18n(request):
    locale = request.session.get('locale', 'en')
    return {'t': _Translator(locale), 'current_locale': locale}
