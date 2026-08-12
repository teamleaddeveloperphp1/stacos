"""Shared format validators for ITR fields (PAN, Aadhaar, TAN, IFSC, PIN code,
mobile number, email, BSR code, challan serial) -- single source of truth for
patterns that were previously duplicated (or missing) across forms.py and
models.py.

Patterns are transcribed verbatim from the authoritative CBDT ITR-1 AY2026-27
JSON schema (myitreturn_live/myitreturn_staging/includes/itrschema/2026-27/
ITR-1/ITR-1_2026.json), NOT from this repo's own data/ay2026-27 schema copy --
the two disagree on PAN (see PAN_INDIVIDUAL_REGEX below) and the authoritative
file was designated the source of truth.

`validate_*` are Django `RegexValidator`s, usable directly on model/form
fields via `validators=[...]`. `clean_*` are helper functions for form
`clean_<field>` methods that need to normalize (strip/uppercase) a value
before validating it -- field-level validators alone would reject a
lowercase PAN before the form gets a chance to upper() it.
"""

from django.core.validators import RegexValidator

# Two distinct PAN patterns in the schema: PersonalInfo.PAN (the taxpayer's
# own PAN) and Verification.AssesseeVerPAN (the verifier's PAN) force the 4th
# character to 'P' (Individual) -- ITR-1 filers/verifiers are always
# individuals. Every other PAN field (PartA_139_8A.PAN, DependentPan,
# DoneePAN, PANofTenant) accepts any entity type via the generic pattern.
PAN_INDIVIDUAL_REGEX = r'^[A-Z]{3}P[A-Z][0-9]{4}[A-Z]$'
PAN_REGEX = r'^[A-Z]{5}[0-9]{4}[A-Z]$'

# EmployerOrDeductorOrCollectDetl.TAN: the schema hardcodes a closed
# alternation of city-code prefixes rather than a generic structural pattern
# -- a syntactically valid TAN whose city code isn't in this list will be
# rejected. Transcribed verbatim; not our choice of leniency.
TAN_REGEX = (
    r'^(HYD|VPN|BBN|BPL|JBP|CHE|CMB|MRI|DEL|CAL|MRT|AHM|BRD|RKT|SRT|BLR|AGR|KNP|'
    r'CHN|TVD|ALD|LKN|MUM|NGP|AMR|JLD|PTL|RTK|KLP|NSK|PNE|PTN|RCH|JDH|JPR|SHL)'
    r'[A-Z][0-9]{5}[A-Z]$'
)

AADHAAR_REGEX = r'^[0-9]{12}$'
AADHAAR_ENROLMENT_ID_REGEX = r'^[0-9]{28}$'
IFSC_REGEX = r'^[A-Z]{4}0[A-Z0-9]{6}$'
PIN_CODE_REGEX = r'^[1-9][0-9]{5}$'

# Address.MobileNo: schema pattern `[1-9]{1}[0-9]{9}|[1-9]{1}[0-9]{4,9}` --
# the first alternative (exactly 10 digits) is a subset of the second (5-10
# digits), so this collapses to "5-10 digits, no leading zero". Looser than
# a strict 10-digit Indian mobile number check.
MOBILE_REGEX = r'^[1-9][0-9]{4,9}$'

# Address.EmailAddress
EMAIL_REGEX = r'^([\.a-zA-Z0-9_\-])+@([a-zA-Z0-9_\-])+(([a-zA-Z0-9_\-])*\.([a-zA-Z0-9_\-])+)+$'

# TaxPayment.BSRCode: last 4 characters are alphanumeric, not pure digits.
BSR_CODE_REGEX = r'^[0-9]{3}[0-9A-Z]{4}$'

# No challan-serial-number field with its own `pattern` exists in the ITR-1
# schema (it's typed as a plain integer there) -- this 5-digit check is our
# own business rule, unchanged.
CHALLAN_SERIAL_REGEX = r'^[0-9]{5}$'

validate_pan_individual = RegexValidator(PAN_INDIVIDUAL_REGEX, 'Enter a valid PAN belonging to an individual.')
validate_pan = RegexValidator(PAN_REGEX, 'Enter a valid PAN.')
validate_tan = RegexValidator(TAN_REGEX, 'Enter a valid TAN.')
validate_aadhaar = RegexValidator(AADHAAR_REGEX, 'Enter a valid 12-digit Aadhaar number.')
validate_aadhaar_enrolment_id = RegexValidator(AADHAAR_ENROLMENT_ID_REGEX, 'Enter a valid 28-digit Aadhaar enrolment ID.')
validate_ifsc = RegexValidator(IFSC_REGEX, 'Enter a valid IFSC code.')
validate_pin_code = RegexValidator(PIN_CODE_REGEX, 'Enter a valid PIN code.')
validate_mobile_number = RegexValidator(MOBILE_REGEX, 'Enter a valid mobile number.')
validate_email_address = RegexValidator(EMAIL_REGEX, 'Enter a valid email address.')
validate_bsr_code = RegexValidator(BSR_CODE_REGEX, 'Enter a valid BSR code.')
validate_challan_serial_no = RegexValidator(CHALLAN_SERIAL_REGEX, 'Challan serial number must be 5 digits.')


def clean_pan_individual(value):
    value = (value or '').strip().upper()
    if value:
        validate_pan_individual(value)
    return value


def clean_pan(value):
    value = (value or '').strip().upper()
    if value:
        validate_pan(value)
    return value


def clean_tan(value):
    value = (value or '').strip().upper()
    if value:
        validate_tan(value)
    return value


def clean_aadhaar(value):
    value = (value or '').strip()
    if value:
        validate_aadhaar(value)
    return value


def clean_aadhaar_enrolment_id(value):
    value = (value or '').strip()
    if value:
        validate_aadhaar_enrolment_id(value)
    return value


def clean_ifsc(value):
    value = (value or '').strip().upper()
    if value:
        validate_ifsc(value)
    return value


def clean_pin_code(value):
    value = (value or '').strip()
    if value:
        validate_pin_code(value)
    return value


def clean_mobile_number(value):
    value = (value or '').strip()
    if value:
        validate_mobile_number(value)
    return value


def clean_email_address(value):
    value = (value or '').strip()
    if value:
        validate_email_address(value)
    return value


def clean_bsr_code(value):
    value = (value or '').strip().upper()
    if value:
        validate_bsr_code(value)
    return value
