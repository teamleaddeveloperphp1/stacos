import base64
import io
import re
import secrets
import string

import qrcode
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

_TOTP_CODE_RE = re.compile(r'^\d{6}$')
_BACKUP_ALPHABET = string.ascii_uppercase + string.digits


def qr_data_uri(data):
    """PNG data URI so the QR never needs its own cacheable endpoint --
    callers still set Cache-Control: no-store on the response itself."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def base32_secret(device):
    """For the manual-entry box next to the QR code."""
    return base64.b32encode(device.bin_key).decode()


def get_or_create_setup_device(user):
    device, _created = TOTPDevice.objects.get_or_create(
        user=user, name='default', confirmed=False,
    )
    return device


def _new_backup_code():
    chars = ''.join(secrets.choice(_BACKUP_ALPHABET) for _ in range(8))
    return f'{chars[:4]}-{chars[4:]}'


def generate_backup_codes(user, count=10):
    """§5.2: regenerating always invalidates every previous code -- delete
    the old device (and its tokens) outright rather than topping up."""
    StaticDevice.objects.filter(user=user, name='backup').delete()
    device = StaticDevice.objects.create(user=user, name='backup', confirmed=True)
    codes = [_new_backup_code() for _ in range(count)]
    StaticToken.objects.bulk_create(StaticToken(device=device, token=code) for code in codes)
    return codes


def is_totp_format(code):
    return bool(_TOTP_CODE_RE.match(code.strip()))


def find_verified_device(user, raw_code):
    """§5.3: one input, detect TOTP (6 digits) vs backup code (anything
    else) by format. Returns the device that accepted the code (already
    consuming a backup token as a side effect) or None. Marking the session
    OTP-verified is the caller's job -- it has to happen *after*
    django.contrib.auth.login() sets request.user, since django_otp.login()
    is a no-op until request.user matches the device's owner."""
    code = (raw_code or '').strip()
    if not code:
        return None

    if is_totp_format(code):
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if device and device.verify_token(code):
            return device
        return None

    normalized = code.replace('-', '').replace(' ', '').upper()
    device = StaticDevice.objects.filter(user=user, name='backup', confirmed=True).first()
    if not device:
        return None
    for token in device.token_set.all():
        if token.token.replace('-', '').upper() == normalized:
            token.delete()  # single-use
            return device
    return None
