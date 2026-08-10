import base64
import io
import re

import qrcode
from django_otp.plugins.otp_totp.models import TOTPDevice

_TOTP_CODE_RE = re.compile(r'^\d{6}$')


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


def is_totp_format(code):
    return bool(_TOTP_CODE_RE.match(code.strip()))


def find_verified_device(user, raw_code):
    """§5.3: verifies a 6-digit TOTP code. Returns the device that accepted
    the code or None. Marking the session OTP-verified is the caller's job --
    it has to happen *after* django.contrib.auth.login() sets request.user,
    since django_otp.login() is a no-op until request.user matches the
    device's owner."""
    code = (raw_code or '').strip()
    if not code or not is_totp_format(code):
        return None

    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device and device.verify_token(code):
        return device
    return None
