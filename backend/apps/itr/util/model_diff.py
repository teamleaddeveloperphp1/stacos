"""Generic ReturnModel tree diffing -- used by the audit log (architecture
mandate 6: every field change is audited with old/new value).

Ported as a straight move from itr/views.py::_diff_model. Not view code:
it's a pure function over two plain dict/list trees, with no Django
dependency, so any writer (web forms, a future API) can reuse it.
"""


def diff_model(old, new, path=''):
    """Recursively diff two ReturnModel dict trees, yielding (path, old, new)
    for every leaf that changed. Lists are compared element-by-element when
    their lengths match (so a single row edit reports as one leaf change per
    field), and as a single whole-list change otherwise (a row added/removed)
    -- diffing an insert/delete field-by-field would misattribute every row
    after the edit point."""
    changes = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in set(old.keys()) | set(new.keys()):
            changes.extend(diff_model(old.get(key), new.get(key), f'{path}.{key}' if path else key))
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for i, (o, n) in enumerate(zip(old, new)):
            changes.extend(diff_model(o, n, f'{path}[{i}]'))
    elif old != new:
        changes.append((path, old, new))
    return changes
