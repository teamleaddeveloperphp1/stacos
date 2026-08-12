"""Structural validation of the generated artifact against the CBDT schema.

Ported from itr1-module/packages/core/src/serialize/jsonSchemaValidator.ts.

NON-NEGOTIABLE 1: the generated JSON is validated inside the generation
pipeline. An unvalidated file is never emitted.

The CBDT schema declares `"$schema": "http://json-schema.org/draft-04/schema#"`,
so we use `jsonschema.Draft4Validator` rather than the auto-detected/default
dialect. Using the wrong dialect silently changes the meaning of
`exclusiveMinimum` and `id`. We also do not attach a `FormatChecker`, mirroring
the TS side's `validateFormats: false` -- the CBDT schema uses format-free
string patterns only.
"""

import multiprocessing
from dataclasses import dataclass, field
from multiprocessing import util as mp_util

from jsonschema import Draft4Validator

from .schema_order import CBDT_SCHEMA

SCHEMA_VERSION = 'ITR-1_2026_Main_V1.1'

# `multiprocessing.Process.start()` unconditionally flushes stdout/stderr
# before forking. Under some WSGI setups (e.g. gunicorn with a broken error
# log after a bad log rotation), that flush itself can raise OSError, which
# would otherwise crash this request even though it has nothing to do with
# the validation being performed. Make the flush best-effort.
_orig_flush_std_streams = mp_util._flush_std_streams


def _safe_flush_std_streams():
    try:
        _orig_flush_std_streams()
    except OSError:
        pass


mp_util._flush_std_streams = _safe_flush_std_streams

# Several of the CBDT schema's own `pattern` regexes (e.g. BankAccountNo,
# LoanAccNoOfBankOrInstnRefNo, the email patterns) use nested quantifiers
# that are catastrophically slow to backtrack on certain inputs -- a
# textbook ReDoS. We cannot rewrite "absolute" schema patterns (see build
# prompt §0), so instead we bound how long the whole structural check may
# run.
#
# A THREAD-based timeout does not work here: CPython's `re` engine holds
# the GIL for the full duration of a single match call, including deep
# backtracking, so even the *timer's own thread* is starved and never
# fires. Only a separate OS process can be forcibly killed once the
# deadline passes, so we run the check in a `multiprocessing.Process` and
# `.terminate()` it on timeout. (Confirmed live: a saved 34-char
# BankAccountNo hung `manage.py runserver` indefinitely, and blocked every
# other request behind it, until the process was killed manually.)
_SCHEMA_VALIDATION_TIMEOUT_SECONDS = 5

_validator = None


def _get_validator():
    global _validator
    if _validator is None:
        _validator = Draft4Validator(CBDT_SCHEMA)
    return _validator


@dataclass
class SchemaViolation:
    instancePath: str
    schemaPath: str
    keyword: str
    message: str
    params: dict = field(default_factory=dict)


@dataclass
class SchemaValidationResult:
    valid: bool
    violations: list = field(default_factory=list)
    schemaVersion: str = SCHEMA_VERSION


def _instance_path(error):
    path = '/' + '/'.join(str(p) for p in error.absolute_path)
    return path if path != '/' else '/'


def _schema_path(error):
    return '/' + '/'.join(str(p) for p in error.absolute_schema_path)


def _to_violation(error):
    keyword = error.validator
    params = {}
    if keyword == 'additionalProperties':
        # jsonschema does not expose the offending key directly; recover it
        # from the message it already computed.
        extra = set(error.instance.keys()) - set(error.schema.get('properties', {}).keys())
        if extra:
            params['additionalProperty'] = sorted(extra)[0]
    elif keyword == 'required':
        # error.validator_value is the full `required` list; recover the
        # specific missing key from the message jsonschema builds internally.
        missing = [k for k in (error.validator_value or []) if k not in (error.instance or {})]
        if missing:
            params['missingProperty'] = missing[0]
    elif keyword == 'enum':
        params['allowedValues'] = error.validator_value

    return SchemaViolation(
        instancePath=_instance_path(error),
        schemaPath=_schema_path(error),
        keyword=keyword,
        message=error.message or 'schema violation',
        params=params,
    )


def _run_validation_subprocess(payload, result_queue):
    """Runs in a child process (see `validate_against_schema`) so it can be
    `.terminate()`-d if a pathological `pattern` regex runs away."""
    validator = _get_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    result_queue.put([_to_violation(e) for e in errors])


def _timeout_result():
    return SchemaValidationResult(
        valid=False,
        violations=[SchemaViolation(
            instancePath='/',
            schemaPath='/',
            keyword='timeout',
            message=(
                'Schema validation could not complete in time. One or more fields likely '
                'contain an unusually long or unusual value -- check bank account numbers, '
                'loan account numbers and email addresses for length or formatting issues.'
            ),
        )],
        schemaVersion=SCHEMA_VERSION,
    )


def validate_against_schema(payload):
    """Validate a generated payload. Never raises on invalid data -- returns the errors.

    Bounded by `_SCHEMA_VALIDATION_TIMEOUT_SECONDS`: see the ReDoS note above
    that constant for why this runs in a subprocess rather than calling
    `iter_errors` directly (or from a thread)."""
    ctx = multiprocessing.get_context('fork')
    result_queue = ctx.Queue()
    process = ctx.Process(target=_run_validation_subprocess, args=(payload, result_queue))
    process.start()
    process.join(timeout=_SCHEMA_VALIDATION_TIMEOUT_SECONDS)

    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()
        return _timeout_result()

    try:
        violations = result_queue.get_nowait()
    except Exception:
        # Child died without producing a result (e.g. killed by the OS OOM
        # killer mid-match) -- fail closed rather than claim success.
        return _timeout_result()

    valid = len(violations) == 0
    return SchemaValidationResult(
        valid=valid,
        violations=violations,
        schemaVersion=SCHEMA_VERSION,
    )


def describe_violation(v):
    """Human-readable one-liner for the validation report."""
    where = 'the document root' if v.instancePath == '/' else v.instancePath
    extra = ''
    if v.keyword == 'additionalProperties':
        extra = f' (unexpected element "{v.params.get("additionalProperty")}")'
    elif v.keyword == 'required':
        extra = f' (missing element "{v.params.get("missingProperty")}")'
    elif v.keyword == 'enum':
        extra = f' (allowed: {v.params.get("allowedValues")})'
    return f'{where}: {v.message}{extra}'
