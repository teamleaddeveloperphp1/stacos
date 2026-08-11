"""The generation pipeline.

Ported from itr1-module/packages/core/src/serialize/generate.ts.

NON-NEGOTIABLE 1: the JSON is validated against the CBDT schema INSIDE this
pipeline. `generate_json` never returns an unvalidated artifact, and
`generate_json_or_throw` refuses to hand one back at all.

Order of operations matters:
  1. compute            -- every derived value, from the model
  2. serialize           -- schema-ordered, pruned artifact
  3. jsonschema (draft-04) -- structural validation of the artifact
  4. rule registry       -- MODEL rules and PAYLOAD rules, tier 3
A blocking failure at (3) or (4) means the download button stays disabled.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.itr.engine.compute import compute as compute_return
from apps.itr.engine.validate import unacknowledged_advisories, validate
from apps.itr.rules.registry import RULE_SET_VERSION

from .json_schema_validator import validate_against_schema
from .serializer import serialize


def _sha256_hex(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass
class GenerationResult:
    """True only when the schema is satisfied AND no Category A rule fires."""

    downloadable: bool
    payload: dict
    json: str
    filename: str
    sha256: str
    computed: dict
    schema: object
    validation: object
    pendingAcknowledgements: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def generate_json(model, opts=None):
    """Run the full generation pipeline for `model`.

    `opts` (all optional): `creationInfo`, `creationDate`, `computed`, `now`
    (a `datetime` used as "now" for the validation report and `meta.generatedAt`).
    """
    opts = opts or {}
    computed = opts.get('computed') if opts.get('computed') is not None else compute_return(model)
    result = serialize(model, {**opts, 'computed': computed})
    payload, json_str, filename = result['payload'], result['json'], result['filename']

    schema = validate_against_schema(payload)
    validation = validate(model, tier=3, payload=payload, computed=computed, now=opts.get('now'))
    pending = [f.ruleId for f in unacknowledged_advisories(validation, model)]

    now = opts.get('now') or datetime.now(timezone.utc)

    return GenerationResult(
        downloadable=schema.valid and len(validation.errors) == 0 and len(validation.ruleErrors) == 0,
        payload=payload,
        json=json_str,
        filename=filename,
        sha256=_sha256_hex(json_str),
        computed=computed,
        schema=schema,
        validation=validation,
        pendingAcknowledgements=pending,
        meta={
            'ruleSetVersion': RULE_SET_VERSION,
            'constantsVersion': computed.get('constantsVersion', ''),
            'schemaVersion': schema.schemaVersion,
            'generatedAt': now.isoformat(),
        },
    )


class GenerationBlockedError(Exception):
    def __init__(self, result):
        self.result = result
        reasons = (
            [f'[schema] {v.instancePath}: {v.message}' for v in result.schema.violations]
            + [f'[{e.ruleId}] {e.message}' for e in result.validation.errors]
            + [f'[{e["ruleId"]}] rule error: {e["error"]}' for e in result.validation.ruleErrors]
        )
        super().__init__('JSON generation blocked:\n  ' + '\n  '.join(reasons))


def generate_json_or_throw(model, opts=None):
    """Use where an invalid artifact must never escape (server download endpoint)."""
    result = generate_json(model, opts)
    if not result.downloadable:
        raise GenerationBlockedError(result)
    return result
