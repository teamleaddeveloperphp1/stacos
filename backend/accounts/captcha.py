import random

from captcha.conf import settings as captcha_settings

# §4.3: 6 alphanumeric characters, excluding visually ambiguous glyphs
# (0/O/o, 1/l/I, 5/S, 2/Z). Uppercase-only alphabet since the letter case
# never affects the compare (captcha.fields.CaptchaField already lowercases
# both sides before checking).
_ALPHABET = 'ABCDEFGHJKLMNPQRTUVWXY346789'


def challenge():
    chars = ''.join(random.choice(_ALPHABET) for _ in range(captcha_settings.CAPTCHA_LENGTH))
    return chars, chars.lower()
