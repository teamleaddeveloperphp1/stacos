"""Round-trip serialize/validate/generate/import test for the golden case.

Ported from the acceptance criteria in itr1-module's build spec section 11/12:
generated JSON must validate against the CBDT schema with zero errors, the
full generation pipeline must report `downloadable=True` for a clean case,
and importing the generated JSON back must recompute to the exact same
figures (zero discrepancies).
"""

from itr.engine.compute import compute
from itr.serialize.generate import generate_json
from itr.serialize.importer import import_from_json
from itr.serialize.json_schema_validator import validate_against_schema
from itr.serialize.schema_order import order_by_schema
from itr.serialize.serializer import serialize

from tests.test_golden import golden_model


def test_golden_serializes_and_orders_cleanly():
    m = golden_model()
    c = compute(m)
    result = serialize(m, {'computed': c})
    payload = result['payload']

    assert 'ITR' in payload
    assert 'ITR1' in payload['ITR']
    # order_by_schema is already applied inside serialize(); re-applying is
    # idempotent and pins that behaviour.
    assert order_by_schema(payload) == payload


def test_golden_json_validates_against_cbdt_schema_with_zero_errors():
    m = golden_model()
    result = serialize(m)
    schema_result = validate_against_schema(result['payload'])

    assert schema_result.violations == []
    assert schema_result.valid is True


def test_golden_generation_pipeline_is_downloadable():
    m = golden_model()
    result = generate_json(m)

    assert result.schema.valid is True
    assert result.schema.violations == []
    assert result.validation.errors == []
    assert result.validation.ruleErrors == []
    assert result.downloadable is True
    assert len(result.sha256) == 64


def test_golden_round_trip_import_has_no_discrepancies():
    m = golden_model()
    result = generate_json(m)

    imported = import_from_json(result.payload, {'tenantId': m['tenantId'], 'returnId': m['returnId']})

    assert imported.unmappedElements == []
    assert imported.discrepancies == []
