"""Minimal JSON-bundle translation (§13: "English and Hindi UI strings from
day one"). Ported in spirit from itr1-module's `i18n/{en,hi}.json` +
`translate(locale, key)` pattern.

Uses a hand-rolled JSON lookup instead of Django's gettext machinery because
this environment has no `msgfmt` (only `gettext-base`, not the full
`gettext` package), so `.po` files could not be compiled to `.mo`. Swapping
to Django's `{% trans %}` later is a drop-in replacement once `msgfmt` is
available -- this module's `translate()` signature intentionally mirrors
`django.utils.translation.gettext`.

SCOPE: covers static UI chrome and screen/section labels only. Individual
form field labels and all 349 rule messages/remediation/source texts remain
English-only -- translating CBDT rule text accurately requires domain
review, not a mechanical string swap, and is a separate, much larger effort.
"""

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent / 'i18n'
_SUPPORTED = ('en', 'hi')
_bundles = {}


def _load(locale):
    if locale not in _bundles:
        path = _DIR / f'{locale}.json'
        _bundles[locale] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return _bundles[locale]


def translate(locale, key):
    """English fallback: an untranslated key never renders as blank."""
    if locale not in _SUPPORTED:
        locale = 'en'
    bundle = _load(locale)
    if key in bundle:
        return bundle[key]
    return _load('en').get(key, key)
