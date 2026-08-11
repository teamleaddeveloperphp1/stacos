"""Schema-driven ordering and pruning.

Ported from itr1-module/packages/core/src/serialize/schemaOrder.ts.

NON-NEGOTIABLE 4: element order follows the schema's declared order. We do not
rely on dict insertion luck -- we walk the CBDT schema and rebuild every
object with its properties in declaration order.

NON-NEGOTIABLE 2: empty nodes are omitted. `None`, `''`, empty lists and
dicts that reduce to empty are dropped; a numeric `0` is emitted only where
the schema marks the property mandatory in its parent.
"""

import json
import os

_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'ay2026-27', 'ITR-1_2026_Main_V1_1.json'
)

with open(_SCHEMA_PATH, encoding='utf-8') as _f:
    CBDT_SCHEMA = json.load(_f)

_ROOT_PROPERTIES = CBDT_SCHEMA['properties']
_ROOT_DEFINITIONS = CBDT_SCHEMA['definitions']


def _deref(node):
    if not node:
        return None
    ref = node.get('$ref')
    if ref:
        name = ref.replace('#/definitions/', '')
        return _deref(_ROOT_DEFINITIONS.get(name))
    # `allOf: [{ $ref: nonEmptyString }]` is a constraint wrapper, not structure.
    return node


def _is_empty_value(v):
    return (
        v is None
        or v == ''
        or (isinstance(v, list) and len(v) == 0)
        or (isinstance(v, dict) and len(v) == 0)
    )


def _order_node(schema, value, keep_empty_object=False):
    """Rebuild `value` in the declaration order of `schema`, pruning empties.

    `keep_empty_object`: when the parent marks this node mandatory, an object
    that reduces to `{}` is still emitted rather than dropped.
    """
    s = _deref(schema)
    if value is None:
        return None

    if isinstance(value, list):
        item_schema = s.get('items') if s else None
        out = [_order_node(item_schema, item) for item in value]
        out = [item for item in out if not _is_empty_value(item)]
        return out if out else None

    if isinstance(value, dict):
        props = s.get('properties') if s else None
        required = set((s.get('required') or []) if s else [])
        src = value
        out = {}

        # Schema-declared properties first, in declaration order.
        keys = list(props.keys()) if props else list(src.keys())
        for key in keys:
            if key not in src:
                continue
            child_schema = props.get(key) if props else None
            child = _order_node(child_schema, src[key], key in required)

            if child is None:
                continue
            # A numeric 0 survives only where the schema marks the property mandatory.
            if child == 0 and not isinstance(child, bool) and key not in required:
                continue
            if _is_empty_value(child) and key not in required:
                continue
            out[key] = child

        # Anything present in the value but absent from the schema is a mapping bug.
        if props:
            for key in src.keys():
                if key not in props and not _is_empty_value(src[key]):
                    raise ValueError(
                        f'Serializer emitted "{key}", which does not exist in the CBDT schema at '
                        'this position. Fix the mapping.'
                    )

        if len(out) == 0 and not keep_empty_object:
            return None
        return out

    return value


def order_by_schema(doc):
    """Order and prune a full `{ ITR: { ITR1: ... } }` document against the schema."""
    out = {}
    for key in _ROOT_PROPERTIES.keys():
        if key not in doc:
            continue
        ordered = _order_node(_ROOT_PROPERTIES[key], doc[key], True)
        if ordered is not None:
            out[key] = ordered
    return out


def property_order(definition):
    """The declared property order of a definition -- used by the docs generator."""
    d = _deref(_ROOT_DEFINITIONS.get(definition))
    if d and d.get('properties'):
        return list(d['properties'].keys())
    return []


def schema_required(definition):
    d = _deref(_ROOT_DEFINITIONS.get(definition))
    return (d.get('required') if d else None) or []
