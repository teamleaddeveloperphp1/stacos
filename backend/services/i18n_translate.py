"""See accounts.i18n_translate / itr.i18n_translate -- same hand-rolled
JSON-bundle convention, one bundle per app."""

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
    if locale not in _SUPPORTED:
        locale = 'en'
    bundle = _load(locale)
    if key in bundle:
        return bundle[key]
    return _load('en').get(key, key)
