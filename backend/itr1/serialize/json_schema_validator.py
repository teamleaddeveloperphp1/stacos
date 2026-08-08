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

from dataclasses import dataclass, field

from jsonschema import Draft4Validator

from .schema_order import CBDT_SCHEMA

SCHEMA_VERSION = 'ITR-1_2026_Main_V1.1'

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


def validate_against_schema(payload):
    """Validate a generated payload. Never raises on invalid data -- returns the errors."""
    validator = _get_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    valid = len(errors) == 0
    return SchemaValidationResult(
        valid=valid,
        violations=[] if valid else [_to_violation(e) for e in errors],
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
